export type Status = 'unreviewed'|'kept'|'hidden'|'followup';
export interface User { authenticated:boolean; username:string|null; can_review:boolean; can_edit:boolean; is_staff:boolean; registration_open:boolean; csrf_token:string }
export interface Tag { id:number; name:string; category:string; word_count?:number; sense_count?:number }
export interface Book { id:number; title:string; edition:string; page_count:number }
export interface POS { code:string;label:string }
export interface Metadata { parts_of_speech:POS[]; tag_categories:string[]; entry_types:string[]; aspects:string[]; animacies:string[]; relation_types:string[] }
export interface Page<T> { items:T[];total:number;page:number;page_size:number;pages:number }
export interface Summary {id:number;lemma:string;pos:string;entry_type:string;aspect:string|null;animacy:string|null;human_status:Status;page_count:number;gloss_preview:string|null;tags:Tag[]}
export interface Example {id:number;sense_id:number;russian:string;english:string;active:number}
export interface Pattern {id:number;sense_id:number;pattern:string;active:number}
export interface Sense {id:number;lexeme_id:number;meaning:string;description:string;active:number;tags:Tag[];examples:Example[];patterns:Pattern[]}
export interface Relation {id:number;source_lexeme_id:number;target_lexeme_id:number;relation_type:string;source_sense_id:number|null;target_sense_id:number|null;direction:'incoming'|'outgoing';notes:string;other_id:number;other_lemma:string;other_pos:string;other_aspect:string|null;other_entry_type:string;other_sense_meaning:string|null}
export interface Component {id:number;expression_id:number;word_id:number;position:number;surface:string;notes:string;word_lemma:string;word_pos:string}
export interface ExternalLink {id:number;lexeme_id:number;label:string;url:string}
export interface Source {book_id?:number;page_id?:number;title:string;edition?:string;pdf_page:number;printed_page:number;surface:string;context:string;count?:number}
export interface Entry extends Summary {notes:string;created_at:string;senses:Sense[];relations:Relation[];components:Component[];occurs_in:{id:number;position:number;surface:string;expression_id:number;expression_lemma:string}[];external_links:ExternalLink[];sources:Source[];sources_total:number;source_page_count:number}
export interface RefPage {book_id:number;title:string;edition:string;page_id:number;pdf_page:number;printed_page:number;occurrence_count:number}
export interface ReviewNext {word:Pick<Entry,'id'|'lemma'|'pos'|'human_status'>|null;total:number;sources:Source[]}
export interface Stats {counts:Record<string,number>;word_status:Record<string,number>;review_status:Record<string,number>}
