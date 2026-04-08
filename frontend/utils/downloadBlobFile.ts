export function downloadBlobFile(blob: Blob, filename: string) {
  const blobURL = window.URL.createObjectURL(blob)
  const tempLink = document.createElement('a')
  tempLink.href = blobURL
  tempLink.setAttribute('download', filename)
  tempLink.click()

  setTimeout(() => {
    URL.revokeObjectURL(blobURL)
    tempLink.remove()
  }, 3600)
}
