import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactElement } from "react";
import { cloneElement } from "react";

type ButtonVariant = "primary" | "secondary";

type BaseProps = {
  variant?: ButtonVariant;
  asChild?: boolean;
};

type ButtonProps = BaseProps &
  ButtonHTMLAttributes<HTMLButtonElement> & {
    children: ReactElement<AnchorHTMLAttributes<HTMLAnchorElement>> | string;
  };

const variantClasses: Record<ButtonVariant, string> = {
  primary: "bg-brand text-white hover:bg-blue-700 disabled:bg-slate-300",
  secondary:
    "border border-line bg-white text-ink hover:bg-surface disabled:text-slate-400",
};

export function Button({
  variant = "primary",
  asChild = false,
  className = "",
  children,
  ...props
}: ButtonProps) {
  const classes = `inline-flex min-h-10 items-center justify-center rounded-md px-4 text-sm font-medium transition ${variantClasses[variant]} ${className}`;

  if (asChild && typeof children !== "string") {
    return cloneElement(children, {
      className: [classes, children.props.className].filter(Boolean).join(" "),
    });
  }

  return (
    <button className={classes} type="button" {...props}>
      {children}
    </button>
  );
}
