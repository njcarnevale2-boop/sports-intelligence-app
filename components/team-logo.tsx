import Image from "next/image";

type TeamLogoProps = {
  src?: string;
  alt: string;
  size?: number;
  className?: string;
};

export default function TeamLogo({ src, alt, size = 56, className = "" }: TeamLogoProps) {
  if (!src) {
    return (
      <div
        className={`flex items-center justify-center rounded-full border border-white/10 bg-white/[0.05] text-[10px] uppercase tracking-[0.2em] text-zinc-400 ${className}`}
        style={{ width: size, height: size }}
      >
        {alt}
      </div>
    );
  }

  return (
    <div className={`overflow-hidden rounded-full border border-white/10 bg-white/[0.04] ${className}`} style={{ width: size, height: size }}>
      <Image src={src} alt={alt} width={size} height={size} className="object-cover" unoptimized />
    </div>
  );
}
