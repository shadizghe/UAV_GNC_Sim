import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Drone Flight Control · GNC Dashboard",
  description:
    "Interactive 6-DOF quadrotor simulator with cascaded PID, EKF state estimation, " +
    "threat modelling, and live tactical display.",
  icons: { icon: "/favicon.svg" },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen overflow-hidden">{children}</body>
    </html>
  );
}
