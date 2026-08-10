import type { Metadata } from "next";
import "./globals.css";
import LayoutShell from "./layout-shell";

export const metadata: Metadata = {
  title: "Sports Intelligence OS",
  description: "Decision support for serious sports bettors.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <LayoutShell>{children}</LayoutShell>
      </body>
    </html>
  );
}
