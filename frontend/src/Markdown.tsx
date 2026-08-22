// Рендер markdown-текста (отчёты проверок). react-markdown не пропускает
// сырой HTML из текста — вывод ИИ нельзя превратить в скрипт на странице.
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export default function Markdown({ text }: { text: string }) {
  return <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>;
}
