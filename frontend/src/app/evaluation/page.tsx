import { redirect } from 'next/navigation';

/** Legacy route — quality evaluation lives in the workbench overview panel. */
export default function LegacyEvaluationRedirect() {
  redirect('/?view=overview&panel=evaluation');
}
