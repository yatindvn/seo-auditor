import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-primary/10 text-primary hover:bg-primary/20",
        secondary:
          "border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80",
        destructive:
          "border-transparent bg-destructive/10 text-destructive dark:bg-destructive/20 hover:bg-destructive/30",
        outline: "text-foreground border-border/80",
        critical: "border-rose-200 bg-rose-500/10 text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-400",
        warning: "border-amber-200 bg-amber-500/10 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-400",
        info: "border-blue-200 bg-blue-500/10 text-blue-700 dark:border-blue-900/60 dark:bg-blue-950/40 dark:text-blue-400",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
