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
  primary:
    "bg-blue-600 text-white shadow-sm shadow-blue-600/20 hover:bg-blue-700 disabled:bg-slate-300",
  secondary:
    "border border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50 disabled:text-slate-400",
};

export function Button({
  variant = "primary",
  asChild = false,
  className = "",
  children,
  ...props
}: ButtonProps) {
  const classes = `inline-flex min-h-10 items-center justify-center rounded-lg px-4 text-sm font-medium transition duration-200 ${variantClasses[variant]} ${className}`;

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
