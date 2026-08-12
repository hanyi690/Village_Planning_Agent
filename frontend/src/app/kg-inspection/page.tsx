import { redirect } from 'next/navigation';

/** Legacy route — planning workbench is now at `/`. */
export default function LegacyKgInspectionRedirect() {
  redirect('/');
}
