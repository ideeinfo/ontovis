import previous from '../../display_labels.json' with {type:'json'};

const zh: Record<string, string> = previous.zh;
const en: Record<string, string> = previous.en;
const previousChinese = new RegExp(Object.keys(zh).sort((a,b)=>b.length-a.length).join('|'), 'g');
const previousEnglish = new RegExp(`(?<![\\w.-])(?:${Object.keys(en).join('|')})(?![\\w-]|\\.\\w)`, 'gi');

// Display historical text alongside current labels without rewriting fixed records.
export function displayText(value: string | null | undefined): string {
  return (value ?? '').replace(previousChinese, term => zh[term])
    .replace(previousEnglish, term => {
      const replacement = en[term.toLowerCase()];
      if (term === term.toUpperCase()) return replacement.toUpperCase();
      return /^[A-Z]/.test(term) ? replacement[0].toUpperCase() + replacement.slice(1) : replacement;
    });
}
