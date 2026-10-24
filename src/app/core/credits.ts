/** Mentions de l'éditeur, affichées dans l'en-tête, le pied de page et la page « À propos ». */
export const CREDITS = {
  company: 'AIT',
  companyLong: 'Artificial Intelligence & Technology',
  ceo: 'PALM Romeo Daratagnan',
  developer: 'PALM Romeo Daratagnan',
  city: 'Ouagadougou',
  country: 'Burkina Faso',
  /** Affichage tel que donné par AIT ; `tel` est le format international pour les liens d'appel. */
  phones: [
    { label: '00226 77 41 91 06', tel: '+22677419106' },
    { label: '00226 73 63 08 82', tel: '+22673630882' },
  ],
  logo: 'ait-logo.png',
  emblem: 'ait-emblem.png',
} as const;
