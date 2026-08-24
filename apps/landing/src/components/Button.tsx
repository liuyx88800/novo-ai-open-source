import React from 'react';

interface ButtonProps {
  variant?: 'primary' | 'secondary' | 'tertiary';
  children: React.ReactNode;
  className?: string;
  onClick?: () => void;
}

const Button: React.FC<ButtonProps> = ({ variant = 'primary', children, className = '', onClick }) => {
  const baseStyles = "rounded-full px-7 py-3 transition-all duration-300 font-medium text-sm flex items-center justify-center gap-2";

  const variants = {
    primary: "bg-[#051A24] text-white custom-shadow-primary hover:scale-[1.02] active:scale-[0.98]",
    secondary: "bg-white text-[#051A24] custom-shadow-secondary hover:bg-slate-50",
    tertiary: "bg-white text-[#051A24] custom-shadow-primary hover:bg-slate-50"
  };

  return (
    <button
      className={`${baseStyles} ${variants[variant]} ${className}`}
      onClick={onClick}
    >
      {children}
    </button>
  );
};

export default Button;
