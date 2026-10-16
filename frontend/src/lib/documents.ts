/** What tells one document from another: the Aktenzeichen, or the file where
 *  there is none. The backend keys documents the same way (#280); 88 indexed
 *  documents have no Aktenzeichen, and keyed on "" they collapsed into one
 *  React key and one selection (#300). */
export function documentKey(doc: { aktenzeichen: string; source_file?: string }): string {
  return doc.aktenzeichen || doc.source_file || "";
}
