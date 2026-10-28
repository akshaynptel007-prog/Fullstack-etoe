import { Link } from 'wouter'

interface Props {
  href: string
  label: string
}

export function PageBackLink({ href, label }: Props) {
  return (
    <Link href={href} className="page-back">
      <span aria-hidden="true">←</span>
      <span>{label}</span>
    </Link>
  )
}
