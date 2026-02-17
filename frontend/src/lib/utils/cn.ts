/**
 * Classname Utility
 * Combines class names conditionally - similar to clsx/cn
 */

export type ClassValue =
  | string
  | number
  | boolean
  | undefined
  | null
  | ClassValue[];

function toVal(mix: ClassValue): string {
  if (typeof mix === 'string' || typeof mix === 'number') {
    return mix.toString();
  }
  if (!mix) return '';
  const res: string[] = [];
  for (const val of Array.isArray(mix) ? mix : [mix]) {
    const out = toVal(val);
    if (out) res.push(out);
  }
  return res.join(' ');
}

/**
 * Combine class names
 *
 * @example
 * cn('foo', 'bar') // 'foo bar'
 * cn('foo', { bar: true, baz: false }) // 'foo bar'
 * cn(['foo', 'bar']) // 'foo bar'
 */
export function cn(...classes: ClassValue[]): string {
  return toVal(classes);
}
