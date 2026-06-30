import { useState, useRef, DragEvent } from 'react'

interface Props {
  onFiles: (files: File[]) => void;
  accept?: string;
  multiple?: boolean;
}

export default function Dropzone({ onFiles, accept, multiple = true }: Props) {
  const [hover, setHover] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = (e: DragEvent) => {
    e.preventDefault(); setHover(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length) onFiles(files);
  };

  return (
    <div
      onDragOver={e => { e.preventDefault(); setHover(true); }}
      onDragLeave={() => setHover(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
      style={{
        border: `2px dashed ${hover ? 'var(--accent)' : 'var(--border)'}`,
        borderRadius: 8, padding: '24px',
        textAlign: 'center', cursor: 'pointer',
        background: hover ? 'rgba(88,166,255,.05)' : 'transparent',
        transition: 'border .2s, background .2s',
      }}
    >
      <div style={{ fontSize: 14, color: 'var(--text)', marginBottom: 4 }}>
        📂 Drop QE files here or click to browse
      </div>
      <div style={{ fontSize: 11, color: 'var(--muted)' }}>
        .in / .out / .dos / .bands / .freq.gp / lambdax.out
      </div>
      <input ref={inputRef} type="file" multiple={multiple} accept={accept}
        style={{ display: 'none' }}
        onChange={e => {
          const files = Array.from(e.target.files || []);
          if (files.length) onFiles(files);
        }}
      />
    </div>
  )
}
