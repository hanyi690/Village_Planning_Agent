/**
 * Button Style Utilities
 * Generate Tailwind CSS classes for button components
 */

export type ButtonVariant = 'primary' | 'secondary' | 'success' | 'danger' | 'warning';
export type ButtonSize = 'sm' | 'md' | 'lg';
export type ButtonRadius = 'sm' | 'md' | 'lg' | 'full';

const variantClasses: Record<ButtonVariant, string> = {
  primary: 'bg-blue-600 hover:bg-blue-700 text-white border-blue-700',
  secondary: 'bg-gray-100 hover:bg-gray-200 text-gray-700 border-gray-300',
  success: 'bg-green-600 hover:bg-green-700 text-white border-green-700',
  danger: 'bg-red-600 hover:bg-red-700 text-white border-red-700',
  warning: 'bg-yellow-500 hover:bg-yellow-600 text-white border-yellow-600',
};

const sizeClasses: Record<ButtonSize, string> = {
  sm: 'px-2.5 py-1 text-sm',
  md: 'px-4 py-2 text-sm',
  lg: 'px-6 py-2.5 text-base',
};

const radiusClasses: Record<ButtonRadius, string> = {
  sm: 'rounded-sm',
  md: 'rounded-md',
  lg: 'rounded-lg',
  full: 'rounded-full',
};

/**
 * Generate button classes
 * @param variant - Button style variant
 * @param size - Button size
 * @param radius - Border radius
 * @returns Tailwind CSS class string
 */
export function getButtonClasses(
  variant: ButtonVariant = 'secondary',
  size: ButtonSize = 'md',
  radius: ButtonRadius = 'md'
): string {
  const classes = [
    'inline-flex',
    'items-center',
    'justify-center',
    'font-medium',
    'border',
    'transition-colors',
    'duration-150',
    'focus:outline-none',
    'focus:ring-2',
    'focus:ring-offset-1',
    'disabled:opacity-50',
    'disabled:cursor-not-allowed',
    variantClasses[variant],
    sizeClasses[size],
    radiusClasses[radius],
  ];

  return classes.join(' ');
}

/**
 * Get icon class for action buttons
 * @param actionId - Action identifier
 * @returns Font Awesome icon class
 */
export function getActionIconClass(actionId: string): string {
  const iconMap: Record<string, string> = {
    approve: 'fa-check',
    cancel: 'fa-times',
    delete: 'fa-trash',
    edit: 'fa-edit',
    view: 'fa-eye',
    download: 'fa-download',
    upload: 'fa-upload',
    share: 'fa-share',
    copy: 'fa-copy',
    refresh: 'fa-sync-alt',
    settings: 'fa-cog',
    info: 'fa-info-circle',
    warning: 'fa-exclamation-triangle',
    success: 'fa-check-circle',
    error: 'fa-times-circle',
    next: 'fa-arrow-right',
    previous: 'fa-arrow-left',
    close: 'fa-times',
    expand: 'fa-expand',
    collapse: 'fa-compress',
  };

  return iconMap[actionId] || 'fa-circle';
}
