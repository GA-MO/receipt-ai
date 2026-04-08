import { useState, useCallback, useRef, useEffect } from 'react'
import { useGesture } from '@use-gesture/react'
import { downloadBlobFile } from '@/lib/downloadBlobFile'
import { ActionIcon, Center, Group, Loader, Text, Tooltip } from '@mantine/core'
import {
  IconDownload,
  IconZoomIn,
  IconZoomOut,
  IconRotateClockwise,
  IconRotate,
  IconZoomReset
} from '@tabler/icons-react'

const ZOOM_STEP = 0.25
const ZOOM_MIN = 0.25
const ZOOM_MAX = 5
const ROTATE_STEP = 90
const MOMENTUM_DECAY = 0.95
const MOMENTUM_STOP_THRESHOLD = 0.5
const DOUBLE_TAP_DELAY = 300
const DOUBLE_TAP_ZOOM = 2

function clampZoom(value: number) {
  return Math.min(Math.max(value, ZOOM_MIN), ZOOM_MAX)
}

function calcMaxPan(
  imgW: number,
  imgH: number,
  containerW: number,
  containerH: number,
  zoom: number,
  rotation: number
): { maxX: number; maxY: number } {
  const isRotated = Math.abs(rotation % 180) === 90
  const scaledW = (isRotated ? imgH : imgW) * zoom
  const scaledH = (isRotated ? imgW : imgH) * zoom
  return {
    maxX: Math.max(0, (scaledW - containerW) / 2),
    maxY: Math.max(0, (scaledH - containerH) / 2)
  }
}

function clampPan(x: number, y: number, maxX: number, maxY: number) {
  return {
    x: Math.max(-maxX, Math.min(maxX, x)),
    y: Math.max(-maxY, Math.min(maxY, y))
  }
}

function calcFitZoom(imgW: number, imgH: number, containerW: number, containerH: number): number {
  if (imgW <= 0 || imgH <= 0 || containerW <= 0 || containerH <= 0) return 1
  return Math.min(containerW / imgW, containerH / imgH, 1)
}

/** Clamp pan for a given zoom value using current image/container/rotation refs */
function clampPanForZoom(
  x: number, y: number, z: number,
  imgSize: { w: number; h: number },
  containerSize: { w: number; h: number },
  rotation: number
) {
  const { maxX, maxY } = calcMaxPan(imgSize.w, imgSize.h, containerSize.w, containerSize.h, z, rotation)
  return clampPan(x, y, maxX, maxY)
}

interface ImageCanvasProps {
  src: string
  alt?: string
  downloadFilename?: string
}

export function ImageCanvas({ src, alt = '', downloadFilename }: ImageCanvasProps) {
  const [zoom, setZoom] = useState(1)
  const [rotation, setRotation] = useState(0)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [isDragging, setIsDragging] = useState(false)
  const [isPinching, setIsPinching] = useState(false)
  const [isMomentum, setIsMomentum] = useState(false)
  const [imgStatus, setImgStatus] = useState<'loading' | 'loaded' | 'error'>('loading')
  const [imgSize, setImgSize] = useState({ w: 0, h: 0 })
  const [containerSize, setContainerSize] = useState({ w: 0, h: 0 })
  const fitZoomRef = useRef(1)
  const containerRef = useRef<HTMLDivElement>(null)
  const momentumRaf = useRef(0)
  const lastTapTime = useRef(0)

  // Stable refs for gesture callbacks (avoid stale closures)
  const zoomRef = useRef(zoom)
  const rotationRef = useRef(rotation)
  const panRef = useRef(pan)
  const imgSizeRef = useRef(imgSize)
  const containerSizeRef = useRef(containerSize)

  useEffect(() => { zoomRef.current = zoom }, [zoom])
  useEffect(() => { rotationRef.current = rotation }, [rotation])
  useEffect(() => { panRef.current = pan }, [pan])
  useEffect(() => { imgSizeRef.current = imgSize }, [imgSize])
  useEffect(() => { containerSizeRef.current = containerSize }, [containerSize])

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const updateSize = () => setContainerSize({ w: el.clientWidth, h: el.clientHeight })
    updateSize()
    const observer = new ResizeObserver(updateSize)
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  // Recalculate fitZoom when container or image size changes (e.g. orientation change)
  useEffect(() => {
    if (imgSize.w <= 0 || imgSize.h <= 0) return
    if (containerSize.w <= 0 || containerSize.h <= 0) return
    fitZoomRef.current = calcFitZoom(imgSize.w, imgSize.h, containerSize.w, containerSize.h)
  }, [imgSize, containerSize])

  useEffect(() => {
    return () => {
      if (momentumRaf.current) cancelAnimationFrame(momentumRaf.current)
    }
  }, [])

  /** Convert client coordinates to position relative to container center */
  const getPointFromClient = useCallback((clientX: number, clientY: number) => {
    const el = containerRef.current
    if (!el) return { x: 0, y: 0 }
    const rect = el.getBoundingClientRect()
    return {
      x: clientX - rect.left - rect.width / 2,
      y: clientY - rect.top - rect.height / 2
    }
  }, [])

  /** Adjust pan so that the point under (cx, cy) stays fixed when zoom changes */
  const zoomTowardPoint = useCallback(
    (prevZoom: number, nextZoom: number, prevPan: { x: number; y: number }, cx: number, cy: number) => {
      const ratio = nextZoom / prevZoom
      const newPan = {
        x: cx * (1 - ratio) + prevPan.x * ratio,
        y: cy * (1 - ratio) + prevPan.y * ratio
      }
      return clampPanForZoom(
        newPan.x, newPan.y, nextZoom,
        imgSizeRef.current, containerSizeRef.current, rotationRef.current
      )
    },
    []
  )

  const clampWithCurrent = useCallback(
    (x: number, y: number) => {
      const { maxX, maxY } = calcMaxPan(
        imgSizeRef.current.w, imgSizeRef.current.h,
        containerSizeRef.current.w, containerSizeRef.current.h,
        zoomRef.current, rotationRef.current
      )
      return clampPan(x, y, maxX, maxY)
    },
    []
  )

  const stopMomentum = useCallback(() => {
    if (momentumRaf.current) {
      cancelAnimationFrame(momentumRaf.current)
      momentumRaf.current = 0
      setIsMomentum(false)
    }
  }, [])

  const startMomentum = useCallback((vx: number, vy: number) => {
    stopMomentum()
    const vel = { x: vx, y: vy }
    let lastTime = 0

    const animate = (timestamp: number) => {
      if (!lastTime) {
        lastTime = timestamp
        momentumRaf.current = requestAnimationFrame(animate)
        return
      }
      const dt = timestamp - lastTime
      lastTime = timestamp

      vel.x *= MOMENTUM_DECAY
      vel.y *= MOMENTUM_DECAY

      if (Math.abs(vel.x) < MOMENTUM_STOP_THRESHOLD && Math.abs(vel.y) < MOMENTUM_STOP_THRESHOLD) {
        momentumRaf.current = 0
        setIsMomentum(false)
        return
      }

      const moveX = vel.x * dt
      const moveY = vel.y * dt
      setPan((prev) => {
        const next = clampWithCurrent(prev.x + moveX, prev.y + moveY)
        if (next.x === prev.x) vel.x = 0
        if (next.y === prev.y) vel.y = 0
        return next
      })
      momentumRaf.current = requestAnimationFrame(animate)
    }
    setIsMomentum(true)
    momentumRaf.current = requestAnimationFrame(animate)
  }, [clampWithCurrent, stopMomentum])

  /** Handle double-tap: toggle between fit zoom and DOUBLE_TAP_ZOOM toward tap point */
  const handleDoubleTap = useCallback((clientX: number, clientY: number) => {
    stopMomentum()
    const point = getPointFromClient(clientX, clientY)
    const currentZoom = zoomRef.current
    const fitZoom = fitZoomRef.current
    const isAtFit = Math.abs(currentZoom - fitZoom) < 0.05

    if (isAtFit) {
      const nextZoom = clampZoom(Math.max(fitZoom * DOUBLE_TAP_ZOOM, 1))
      const newPan = zoomTowardPoint(currentZoom, nextZoom, panRef.current, point.x, point.y)
      setZoom(nextZoom)
      setPan(newPan)
    } else {
      setZoom(fitZoom)
      setPan({ x: 0, y: 0 })
    }
  }, [getPointFromClient, zoomTowardPoint, stopMomentum])

  useGesture(
    {
      onDrag: ({ active, movement: [mx, my], velocity: [vx, vy], direction: [dx, dy], last, pinching, cancel, tap, event, memo }) => {
        if (pinching) {
          cancel()
          return
        }

        // Double-tap detection via drag's filterTaps
        if (tap) {
          const e = event as PointerEvent
          const now = Date.now()
          if (now - lastTapTime.current < DOUBLE_TAP_DELAY) {
            handleDoubleTap(e.clientX, e.clientY)
            lastTapTime.current = 0
          } else {
            lastTapTime.current = now
          }
          return
        }

        if (!memo) {
          const { maxX, maxY } = calcMaxPan(
            imgSizeRef.current.w, imgSizeRef.current.h,
            containerSizeRef.current.w, containerSizeRef.current.h,
            zoomRef.current, rotationRef.current
          )
          if (maxX <= 0 && maxY <= 0) return
          memo = { ...panRef.current }
          stopMomentum()
        }

        setIsDragging(active)

        if (active) {
          setPan(clampWithCurrent(memo.x + mx, memo.y + my))
        }

        if (last) {
          const momentumX = vx * dx
          const momentumY = vy * dy
          if (Math.abs(momentumX) > 0.1 || Math.abs(momentumY) > 0.1) {
            startMomentum(momentumX, momentumY)
          }
        }

        return memo
      },

      onPinch: ({ offset: [scale], origin: [ox, oy], active }) => {
        setIsPinching(active)
        const nextZoom = clampZoom(scale)

        // Use React state setter to get latest prev values (no stale ref issues)
        setZoom((prevZoom) => {
          if (prevZoom === nextZoom) return prevZoom
          const point = getPointFromClient(ox, oy)
          setPan((prevPan) =>
            zoomTowardPoint(prevZoom, nextZoom, prevPan, point.x, point.y)
          )
          return nextZoom
        })
      },

      onWheel: ({ event, delta: [, dy] }) => {
        event.preventDefault()
        const wheelEvent = event as WheelEvent
        const point = getPointFromClient(wheelEvent.clientX, wheelEvent.clientY)

        setZoom((prevZoom) => {
          const nextZoom = clampZoom(prevZoom * (1 - dy * 0.001))
          setPan((prevPan) =>
            zoomTowardPoint(prevZoom, nextZoom, prevPan, point.x, point.y)
          )
          return nextZoom
        })
      }
    },
    {
      target: containerRef,
      drag: { filterTaps: true },
      pinch: { from: () => [zoomRef.current, 0] },
      wheel: { eventOptions: { passive: false } }
    }
  )

  const handleImageLoad = useCallback((e: React.SyntheticEvent<HTMLImageElement>) => {
    const img = e.currentTarget
    const w = img.naturalWidth
    const h = img.naturalHeight
    setImgSize({ w, h })
    setImgStatus('loaded')

    const el = containerRef.current
    if (el) {
      const fit = calcFitZoom(w, h, el.clientWidth, el.clientHeight)
      fitZoomRef.current = fit
      setZoom(fit)
    }
  }, [])

  const handleImageError = useCallback(() => {
    setImgStatus('error')
  }, [])

  const clampWithParams = useCallback(
    (x: number, y: number, z: number, r: number) => {
      const { maxX, maxY } = calcMaxPan(imgSize.w, imgSize.h, containerSize.w, containerSize.h, z, r)
      return clampPan(x, y, maxX, maxY)
    },
    [imgSize, containerSize]
  )

  const handleZoomIn = useCallback(() => {
    setZoom((prev) => {
      const next = clampZoom(prev + ZOOM_STEP)
      setPan((p) => clampWithParams(p.x, p.y, next, rotation))
      return next
    })
  }, [rotation, clampWithParams])

  const handleZoomOut = useCallback(() => {
    setZoom((prev) => {
      const next = clampZoom(prev - ZOOM_STEP)
      setPan((p) => clampWithParams(p.x, p.y, next, rotation))
      return next
    })
  }, [rotation, clampWithParams])

  const handleRotateCW = useCallback(() => {
    setRotation((prev) => {
      const next = prev + ROTATE_STEP
      setPan((p) => clampWithParams(p.x, p.y, zoom, next))
      return next
    })
  }, [zoom, clampWithParams])

  const handleRotateCCW = useCallback(() => {
    setRotation((prev) => {
      const next = prev - ROTATE_STEP
      setPan((p) => clampWithParams(p.x, p.y, zoom, next))
      return next
    })
  }, [zoom, clampWithParams])

  const handleReset = useCallback(() => {
    stopMomentum()
    setZoom(fitZoomRef.current)
    setRotation(0)
    setPan({ x: 0, y: 0 })
  }, [stopMomentum])

  const handleDownload = useCallback(async () => {
    try {
      const res = await fetch(src)
      const blob = await res.blob()
      downloadBlobFile(blob, downloadFilename ?? 'image')
    } catch {
      window.open(src, '_blank')
    }
  }, [src, downloadFilename])

  const { maxX, maxY } = calcMaxPan(imgSize.w, imgSize.h, containerSize.w, containerSize.h, zoom, rotation)
  const isPannable = maxX > 0 || maxY > 0
  const zoomPercent = Math.round(zoom * 100)
  const isAnimating = isDragging || isPinching || isMomentum

  return (
    <div className='relative h-full w-full overflow-hidden bg-gray-100'>
      {/* Toolbar */}
      <div className='absolute bottom-4 z-10 w-full text-center'>
        <Group gap='xs' className='mx-auto w-fit rounded-lg bg-white px-3 py-2 shadow-md'>
          <Tooltip label='ย่อ' position='bottom'>
            <ActionIcon
              variant='subtle'
              color='gray'
              onClick={handleZoomOut}
              disabled={zoom <= ZOOM_MIN}
            >
              <IconZoomOut size={18} />
            </ActionIcon>
          </Tooltip>

          <Text size='sm' fw={500} w={45} ta='center'>
            {zoomPercent}%
          </Text>

          <Tooltip label='ขยาย' position='bottom'>
            <ActionIcon
              variant='subtle'
              color='gray'
              onClick={handleZoomIn}
              disabled={zoom >= ZOOM_MAX}
            >
              <IconZoomIn size={18} />
            </ActionIcon>
          </Tooltip>

          <div className='mx-1 h-5 w-px bg-gray-300' />

          <Tooltip label='หมุนซ้าย' position='bottom'>
            <ActionIcon variant='subtle' color='gray' onClick={handleRotateCCW}>
              <IconRotate size={18} />
            </ActionIcon>
          </Tooltip>

          <Tooltip label='หมุนขวา' position='bottom'>
            <ActionIcon variant='subtle' color='gray' onClick={handleRotateCW}>
              <IconRotateClockwise size={18} />
            </ActionIcon>
          </Tooltip>

          <div className='mx-1 h-5 w-px bg-gray-300' />

          <Tooltip label='รีเซ็ต' position='bottom'>
            <ActionIcon variant='subtle' color='gray' onClick={handleReset}>
              <IconZoomReset size={18} />
            </ActionIcon>
          </Tooltip>

          <div className='mx-1 h-5 w-px bg-gray-300' />

          <Tooltip label='ดาวน์โหลด' position='bottom'>
            <ActionIcon variant='subtle' color='gray' onClick={handleDownload}>
              <IconDownload size={18} />
            </ActionIcon>
          </Tooltip>
        </Group>
      </div>

      {imgStatus === 'loading' && (
        <Center className='absolute inset-0 z-0'>
          <Loader size='md' />
        </Center>
      )}

      {imgStatus === 'error' && (
        <Center className='absolute inset-0 z-0'>
          <Text c='dimmed'>ไม่สามารถโหลดรูปภาพได้</Text>
        </Center>
      )}

      {/* Image */}
      <div
        ref={containerRef}
        className='flex h-full w-full items-center justify-center overflow-hidden'
        style={{
          cursor: isPannable ? (isDragging ? 'grabbing' : 'grab') : 'default',
          touchAction: 'none'
        }}
      >
        <img
          src={src}
          alt={alt}
          draggable={false}
          onLoad={handleImageLoad}
          onError={handleImageError}
          className='max-h-none max-w-none select-none'
          style={{
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom}) rotate(${rotation}deg)`,
            transition: isAnimating ? 'none' : 'transform 200ms ease-out',
            opacity: imgStatus === 'loaded' ? 1 : 0
          }}
        />
      </div>
    </div>
  )
}
