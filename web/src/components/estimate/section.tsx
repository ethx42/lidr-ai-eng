import type { ReactNode } from "react";

export const Section = ({ title, description, children }: { title: string; description?: string; children: ReactNode }) => (
  <section className="flex min-w-0 flex-col gap-2">
    <div className="flex flex-col gap-1">
      <h3 className="text-base font-semibold">{title}</h3>
      {description && <p className="text-sm text-muted-foreground">{description}</p>}
    </div>
    {children}
  </section>
);

export const Empty = ({ children }: { children: ReactNode }) => <p className="text-sm text-muted-foreground">{children}</p>;
