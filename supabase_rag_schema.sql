create extension if not exists vector;

create table if not exists public.rag_chunks (
    id bigserial primary key,
    source_name text not null,
    file_unique_id text not null,
    chunk_index integer not null,
    content text not null,
    embedding vector(384) not null,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists rag_chunks_file_unique_id_idx
    on public.rag_chunks (file_unique_id);

create index if not exists rag_chunks_embedding_idx
    on public.rag_chunks
    using ivfflat (embedding vector_cosine_ops)
    with (lists = 100);

create or replace function public.match_rag_chunks(
    query_embedding vector(384),
    match_count int default 5,
    similarity_threshold float default 0.25
)
returns table (
    id bigint,
    source_name text,
    chunk_index integer,
    content text,
    similarity float
)
language sql
stable
as $$
    select
        rag_chunks.id,
        rag_chunks.source_name,
        rag_chunks.chunk_index,
        rag_chunks.content,
        1 - (rag_chunks.embedding <=> query_embedding) as similarity
    from public.rag_chunks
    where 1 - (rag_chunks.embedding <=> query_embedding) >= similarity_threshold
    order by rag_chunks.embedding <=> query_embedding
    limit match_count;
$$;
