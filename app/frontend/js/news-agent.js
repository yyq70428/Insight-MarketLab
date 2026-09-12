export function citationIsValid(citation,sources){return sources.some(source=>source.id===citation.sourceId&&source.type===citation.type)}
