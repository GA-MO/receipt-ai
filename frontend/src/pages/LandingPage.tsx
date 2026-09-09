import { Link } from "react-router-dom";
import { motion } from "motion/react";
import {
  IconArrowRight,
  IconBuildingStore,
  IconChecks,
  IconInbox,
  IconLayoutGrid,
  IconReceipt,
  IconSparkles,
  IconUpload,
} from "@tabler/icons-react";

/**
 * The fork in the road: daily work on the left, the demo surface on the right.
 *
 * Two doors, one decision — so the page carries no navigation of its own and
 * nothing else competes for the click. The divider is a receipt perforation
 * because that is what this product is made of, and it makes the split read as
 * one torn slip rather than two unrelated cards.
 */

type DoorProps = {
  side: "left" | "right";
  to: string;
  eyebrow: string;
  title: string;
  blurb: string;
  points: { icon: typeof IconInbox; text: string }[];
  cta: string;
  icon: typeof IconInbox;
};

function Door({ side, to, eyebrow, title, blurb, points, cta, icon: Icon }: DoorProps) {
  return (
    <motion.div
      className="landing-door"
      data-side={side}
      initial={{ opacity: 0, y: 18 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: side === "left" ? 0.05 : 0.13, ease: [0.22, 1, 0.36, 1] }}
    >
      <Link to={to} className="landing-door-link">
        <span className="landing-door-glow" aria-hidden />
        <span className="landing-door-icon">
          <Icon size={26} />
        </span>
        <span className="landing-eyebrow">{eyebrow}</span>
        <h2 className="landing-door-title">{title}</h2>
        <p className="landing-door-blurb">{blurb}</p>
        <ul className="landing-points">
          {points.map((p) => (
            <li key={p.text}>
              <p.icon size={15} />
              <span>{p.text}</span>
            </li>
          ))}
        </ul>
        <span className="landing-cta">
          {cta}
          <IconArrowRight size={17} />
        </span>
      </Link>
    </motion.div>
  );
}

export default function LandingPage() {
  return (
    <div className="flow-root landing-root">
      <div className="landing-wrap">
        <motion.header
          className="landing-head"
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
        >
          <span className="flow-brand-dot">
            <IconReceipt size={15} />
          </span>
          <div>
            <div className="landing-brand">Receipt AI</div>
            <div className="landing-brand-sub">Thai Receipt Intelligence</div>
          </div>
        </motion.header>

        <motion.div
          className="landing-lede"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.06, ease: [0.22, 1, 0.36, 1] }}
        >
          <h1>
            วันนี้เริ่มที่ <span className="flow-title-grad">ตรงไหนดี</span>
          </h1>
          <p>เลือกโหมดที่ต้องการ — ทำงานจริงกับใบเสร็จของเดือนนี้ หรือดูตัวอย่างว่าระบบทำงานยังไง</p>
        </motion.div>

        <div className="landing-split">
          <Door
            side="left"
            to="/inbox"
            eyebrow="ใช้งานประจำวัน"
            title="โหมดทำงาน"
            blurb="อัปโหลด ตรวจทาน และปิดยอดรายเดือนของแต่ละร้าน พร้อมเก็บรูปไว้เป็นหลักฐานย้อนหลัง"
            points={[
              { icon: IconInbox, text: "กล่องเข้า จัดกลุ่มใบเสร็จอัตโนมัติ" },
              { icon: IconChecks, text: "ตรวจทานทีละใบ แก้ไขและอนุมัติ" },
              { icon: IconBuildingStore, text: "ร้านค้า รอบเดือน และยอดรวมสินค้า" },
            ]}
            cta="ไปที่กล่องเข้า"
            icon={IconLayoutGrid}
          />

          <div className="landing-perf" aria-hidden>
            <span className="landing-perf-notch landing-perf-notch--top" />
            <span className="landing-perf-line" />
            <span className="landing-perf-or">หรือ</span>
            <span className="landing-perf-line" />
            <span className="landing-perf-notch landing-perf-notch--bottom" />
          </div>

          <Door
            side="right"
            to="/flow"
            eyebrow="สาธิตให้ดูใน 30 วินาที"
            title="โหมดสาธิต"
            blurb="ลากใบเสร็จทั้งกองเข้ามาครั้งเดียว แล้วดู AI แยกร้านและสรุปสินค้ากับจำนวนให้ต่อหน้า"
            points={[
              { icon: IconUpload, text: "วางรูปพร้อมกันทั้งเดือน" },
              { icon: IconSparkles, text: "อ่านลายมือและตัวย่อได้เอง" },
              { icon: IconReceipt, text: "ได้ตารางสินค้า × จำนวน ทันที" },
            ]}
            cta="เริ่มสาธิต"
            icon={IconSparkles}
          />
        </div>
      </div>
    </div>
  );
}
