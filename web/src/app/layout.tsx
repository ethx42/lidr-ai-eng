import type { Metadata } from "next";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import { ThemeProvider } from "next-themes";
import { ServiceContextProvider } from "@/components/service-context";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";

export const metadata: Metadata = {
  title: "Estimator",
  description: "Turn a meeting transcript into a project estimate",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${GeistSans.variable} ${GeistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <body className="min-h-full flex flex-col">
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
          <TooltipProvider>
            <ServiceContextProvider>{children}</ServiceContextProvider>
          </TooltipProvider>
          {/* Below the 48 px header. */}
          <Toaster position="top-right" offset={{ top: 56 }} mobileOffset={{ top: 56 }} />
        </ThemeProvider>
      </body>
    </html>
  );
}
