import Image from "next/image";
import { useMemo, useState } from "react";

type TeamLogoProps = {
  src?: string;
  alt: string;
  size?: number;
  className?: string;
};

export default function TeamLogo({ src, alt, size = 56, className = "" }: TeamLogoProps) {
  const [imageFailed, setImageFailed] = useState(false);
  const fallbackLabel = useMemo(() => {
    const trimmed = (alt || "").trim();
    if (!trimmed) return "NFL";
    if (trimmed.length <= 4 && !trimmed.includes(" ")) return trimmed.toUpperCase();
    return trimmed
      .split(/\s+/)
      .slice(0, 3)
      .map((word) => word[0])
      .join("")
      .toUpperCase();
  }, [alt]);

  if (!src || imageFailed) {
    return (
      <div
        className={`flex items-center justify-center rounded-full border border-white/10 bg-white/[0.05] text-[10px] uppercase tracking-[0.2em] text-zinc-400 ${className}`}
        style={{ width: size, height: size }}
      >
        {fallbackLabel}
      </div>
    );
  }

  return (
    <div className={`overflow-hidden rounded-full border border-white/10 bg-white/[0.04] ${className}`} style={{ width: size, height: size }}>
      <Image
        src={src}
        alt={alt}
        width={size}
        height={size}
        className="object-cover"
        unoptimized
        onError={() => setImageFailed(true)}
      />
    </div>
  );
}
