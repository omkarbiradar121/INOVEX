import os
import re
import math
import numpy as np
import pymupdf  # PyMuPDF
from django.conf import settings
from .models import Machine, Manual, ManualChunk

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:
    genai = None


def get_gemini_client():
    api_key = getattr(settings, 'GEMINI_API_KEY', '') or os.getenv('GEMINI_API_KEY', '')
    if not api_key or not genai:
        return None
    try:
        return genai.Client(api_key=api_key)
    except Exception:
        return None


def generate_embedding(text: str) -> list:
    """
    Generate embedding for text using gemini-embedding-001,
    with a deterministic fallback if API is not accessible or offline.
    """
    client = get_gemini_client()
    if client:
        try:
            res = client.models.embed_content(
                model=getattr(settings, 'GEMINI_EMBEDDING_MODEL', 'gemini-embedding-001'),
                contents=text
            )
            if hasattr(res, 'embeddings') and res.embeddings:
                return list(res.embeddings[0].values)
        except Exception as e:
            # Fall back to deterministic vector if network/quota issue
            pass

    # Deterministic 128-dim bag-of-words / char hash embedding fallback
    words = re.findall(r'\b[a-zA-Z0-9_-]+\b', text.lower())
    vec = np.zeros(128, dtype=np.float32)
    for w in words:
        h = abs(hash(w)) % 128
        vec[h] += 1.0
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec.tolist()


def extract_and_chunk_pdf(pdf_path: str, chunk_size: int = 700, chunk_overlap: int = 100) -> list:
    """
    Extract text page by page using PyMuPDF and split into chunks with 1-based page numbers.
    Returns list of dicts:
    [{'page_number': 1, 'chunk_index': 0, 'content': '...'}]
    """
    doc = pymupdf.open(pdf_path)
    all_chunks = []
    chunk_index = 0

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        page_num = page_idx + 1  # 1-based page number
        text = page.get_text() or ''
        text = text.strip()
        if not text:
            continue

        # Split text into manageable paragraphs/sentences
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        if not paragraphs:
            paragraphs = [text]

        current_chunk = ""
        for para in paragraphs:
            if len(current_chunk) + len(para) <= chunk_size:
                current_chunk = f"{current_chunk}\n\n{para}".strip()
            else:
                if current_chunk:
                    all_chunks.append({
                        'page_number': page_num,
                        'chunk_index': chunk_index,
                        'content': current_chunk
                    })
                    chunk_index += 1
                current_chunk = para

        if current_chunk:
            all_chunks.append({
                'page_number': page_num,
                'chunk_index': chunk_index,
                'content': current_chunk
            })
            chunk_index += 1

    doc.close()
    return all_chunks


def index_manual(manual: Manual) -> int:
    """
    Extracts text, creates chunks, computes embeddings, and saves ManualChunk records.
    """
    if not manual.file or not os.path.exists(manual.file.path):
        return 0

    # Delete any existing chunks for this manual
    manual.chunks.all().delete()

    raw_chunks = extract_and_chunk_pdf(manual.file.path)
    manual.page_count = max([c['page_number'] for c in raw_chunks], default=0)
    manual.save()

    created_chunks = []
    for c in raw_chunks:
        emb = generate_embedding(c['content'])
        chunk_obj = ManualChunk(
            manual=manual,
            machine=manual.machine,
            document_id=manual.document_id,
            target_machine_id=manual.machine.machine_id,
            revision=manual.revision,
            page_number=c['page_number'],
            chunk_index=c['chunk_index'],
            content=c['content'],
            embedding=emb
        )
        created_chunks.append(chunk_obj)

    ManualChunk.objects.bulk_create(created_chunks)
    manual.is_indexed = True
    manual.save()
    return len(created_chunks)


def cosine_similarity(v1, v2):
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    a = np.array(v1, dtype=np.float32)
    b = np.array(v2, dtype=np.float32)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def retrieve_relevant_chunks(machine_id: str, question: str, top_k: int = 5) -> list:
    """
    Strictly filters chunks by machine_id (Never retrieves another machine's passages).
    Ranks using hybrid search: embedding cosine similarity + keyword matching.
    """
    # HARD FILTER: machine_id must match strictly
    candidate_chunks = list(ManualChunk.objects.filter(machine__machine_id=machine_id).select_related('manual'))
    if not candidate_chunks:
        return []

    q_embedding = generate_embedding(question)
    q_words = set(re.findall(r'\b[a-zA-Z0-9_-]+\b', question.lower()))

    # Error code patterns e.g. E17, E31, etc.
    error_codes = set(re.findall(r'\b[eE]\d+\b', question.upper()))

    scored_chunks = []
    for chunk in candidate_chunks:
        vec_score = cosine_similarity(q_embedding, chunk.embedding)
        
        # Keyword match score
        content_lower = chunk.content.lower()
        content_upper = chunk.content.upper()
        
        kw_score = 0.0
        # High boost for exact error code matches
        for ec in error_codes:
            if ec in content_upper:
                kw_score += 2.0
                
        # Word overlap boost
        overlap = sum(1 for w in q_words if w in content_lower)
        kw_score += (overlap / max(len(q_words), 1)) * 0.5

        total_score = vec_score + kw_score
        scored_chunks.append((total_score, chunk))

    scored_chunks.sort(key=lambda x: x[0], reverse=True)
    return [c for score, c in scored_chunks[:top_k]]


def extract_relevant_passage(content: str, question: str, max_len: int = 280) -> str:
    """
    Extracts the most relevant sentence or lines from chunk content matching the question terms,
    ensuring supporting citations display the exact evidence text rather than arbitrary page headers.
    """
    error_codes = re.findall(r'\b[eE]\d+\b', question.upper())
    lines = [l.strip() for l in content.split('\n') if l.strip()]

    # Priority 1: Match error codes (e.g. E31, E17, E24, E42, E08)
    if error_codes:
        for idx, line in enumerate(lines):
            for ec in error_codes:
                if re.search(r'\b' + re.escape(ec) + r'\b', line, re.IGNORECASE):
                    # Combine the code line and the following response lines
                    snippet_lines = lines[idx:idx + 4]
                    snippet = " | ".join(snippet_lines)
                    if len(snippet) > max_len:
                        snippet = snippet[:max_len].rsplit(' ', 1)[0] + '...'
                    return snippet

    # Priority 2: Best keyword overlap paragraph
    q_words = set(re.findall(r'\b[a-zA-Z0-9_-]{4,}\b', question.lower()))
    paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
    best_para = ""
    best_overlap = -1
    for p in paragraphs:
        p_clean = p.replace('\n', ' ')
        p_lower = p_clean.lower()
        overlap = sum(1 for w in q_words if w in p_lower)
        if overlap > best_overlap:
            best_overlap = overlap
            best_para = p_clean

    if best_para and best_overlap > 0:
        if len(best_para) > max_len:
            best_para = best_para[:max_len].rsplit(' ', 1)[0] + '...'
        return best_para

    # Fallback: clean snippet from start of content
    fallback = content.replace('\n', ' ').strip()
    if len(fallback) > max_len:
        fallback = fallback[:max_len].rsplit(' ', 1)[0] + '...'
    return fallback


def ask_rag_pipeline(machine_id: str, question: str) -> dict:
    """
    Full RAG pipeline:
    1. Retrieve machine-filtered chunks
    2. Check relevance
    3. Generate grounded answer with Gemini
    4. Format answer, citations, and status
    """
    try:
        machine = Machine.objects.get(machine_id=machine_id)
    except Machine.DoesNotExist:
        return {
            'answer': "Machine not found in registry.",
            'status': 'insufficient-evidence',
            'citations': []
        }

    relevant_chunks = retrieve_relevant_chunks(machine_id, question, top_k=6)
    
    if not relevant_chunks:
        return {
            'answer': "The available manuals do not contain enough information to answer this question.",
            'status': 'insufficient-evidence',
            'citations': []
        }

    # Prepare excerpts
    context_blocks = []
    citations_map = {}
    for idx, c in enumerate(relevant_chunks):
        pdf_url = c.manual.file.url if c.manual and c.manual.file else ''
        citation_key = f"{c.document_id}-P{c.page_number}"
        if citation_key not in citations_map:
            citations_map[citation_key] = {
                'document_id': c.document_id,
                'document_name': c.manual.title if c.manual else c.document_id,
                'revision': c.revision,
                'page_number': c.page_number,
                'passage_text': extract_relevant_passage(c.content, question),
                'pdf_url': f"{pdf_url}#page={c.page_number}" if pdf_url else f"#page={c.page_number}"
            }
        context_blocks.append(
            f"--- EXCERPT {idx+1} ---\n"
            f"Document ID: {c.document_id}\n"
            f"Document Title: {c.manual.title if c.manual else ''}\n"
            f"Revision: {c.revision}\n"
            f"PDF Page: {c.page_number}\n"
            f"Content:\n{c.content}\n"
        )

    context_str = "\n".join(context_blocks)

    system_instruction = (
        f"You are the Manufacturing Manual Assistant for machine '{machine.name}' ({machine.machine_id}).\n"
        "Your task is to answer the maintenance or operational question based ONLY on the supplied manual excerpts.\n\n"
        "STRICT GROUNDING RULES:\n"
        "1. Generate your answer using ONLY the explicit evidence in the EXCERPTS below.\n"
        "2. If the excerpts do not contain sufficient evidence to answer the question, you MUST respond EXACTLY with:\n"
        "   'The available manuals do not contain enough information to answer this question.'\n"
        "3. Never invent facts, procedures, specs, or citations. Do not invent torque specifications, optical curtains, or missing repair steps.\n"
        "4. Never use general model knowledge as maintenance guidance.\n"
        "5. For every fact, cite the document and page, e.g. [Document ID, Rev, Page X].\n"
        "6. If the answer requires information from both HP-200 manuals, explicitly cite both documents.\n"
        "7. If information is absent from the supplied manuals (such as tightening torque, internal repair steps, resolution details not specified), explicitly state that it is not provided.\n"
        "8. Focus strictly on the direct positive meaning of the question for the target machine. State directly what the parameter or error code actually means. Do NOT include negative disclaimers about what a code is NOT (e.g. do NOT mention 'guard-open' or contrast with other machines when defining AC-90 error codes).\n"
    )

    prompt = (
        f"{system_instruction}\n\n"
        f"EXCERPTS FROM MANUALS FOR {machine.machine_id}:\n"
        f"{context_str}\n\n"
        f"ENGINEER'S QUESTION:\n{question}\n\n"
        "GROUNDED ANSWER:"
    )

    client = get_gemini_client()
    answer_text = ""

    if client:
        try:
            model_name = getattr(settings, 'GEMINI_MODEL_NAME', 'gemini-flash-lite-latest')
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    temperature=0.1,  # Low temperature for deterministic factual answers
                    max_output_tokens=1000
                )
            )
            if response and response.text:
                answer_text = response.text.strip()
        except Exception as e:
            # Fall back to grounded passage extraction if network fails
            pass

    # If Gemini couldn't be contacted or produced no answer, fallback to strict passage extraction
    if not answer_text:
        STOP_WORDS = {'what', 'when', 'where', 'which', 'who', 'whom', 'why', 'how',
                      'does', 'mean', 'means', 'explain', 'describe', 'procedure',
                      'recommended', 'please', 'tell', 'about', 'with', 'from', 'this',
                      'that', 'these', 'those', 'machine', 'system', 'manual', 'manuals'}
        
        q_lower = question.lower()
        error_matches = re.findall(r'\b[eE]\d+\b', question.upper())
        q_keywords = [w for w in re.findall(r'\b[a-zA-Z0-9_-]+\b', q_lower) if w not in STOP_WORDS and len(w) >= 4]

        # Check for unsupported technical terms not present in any machine manual
        all_manual_text = " ".join([c.content.lower() for c in relevant_chunks])
        unmatched_specific_terms = [w for w in q_keywords if w not in all_manual_text]
        
        # If crucial query terms are missing from the manuals, it is unsupported
        if len(unmatched_specific_terms) >= 2 or (len(q_keywords) > 0 and len(unmatched_specific_terms) / len(q_keywords) > 0.4):
            answer_text = "The available manuals do not contain enough information to answer this question."
        else:
            matched_chunks = []
            for c in relevant_chunks:
                c_upper = c.content.upper()
                c_lower = c.content.lower()
                if error_matches and any(em in c_upper for em in error_matches):
                    matched_chunks.append(c)
                elif not error_matches and q_keywords:
                    overlap = sum(1 for kw in q_keywords if kw in c_lower)
                    if overlap >= 2 or (len(q_keywords) == 1 and overlap == 1):
                        matched_chunks.append(c)

            if not matched_chunks:
                answer_text = "The available manuals do not contain enough information to answer this question."
            else:
                answer_text = (
                    f"Based on the available manuals for {machine.machine_id}:\n\n" +
                    "\n\n".join([f"[{c.document_id}, {c.revision}, Page {c.page_number}]: {extract_relevant_passage(c.content, question)}" for c in matched_chunks[:2]])
                )

    # Check for insufficient evidence response
    insufficient_phrase = "the available manuals do not contain enough information to answer this question"
    if insufficient_phrase in answer_text.lower():
        status = 'insufficient-evidence'
        citations = []
    else:
        status = 'answered'
        # Filter citations to include only those relevant or referenced in the answer
        final_citations = []
        q_tokens = set(re.findall(r'\b[eE]\d+\b', question.upper()))
        
        for cit_key, cit_data in citations_map.items():
            doc_id = cit_data['document_id']
            page_num = cit_data['page_number']
            
            # Check if cited in answer text or matches key error codes
            is_referenced = (f"{doc_id}" in answer_text and f"Page {page_num}" in answer_text) or \
                            (f"{doc_id}" in answer_text and f"page {page_num}" in answer_text.lower())
            has_error_code = any(re.search(r'\b' + re.escape(ec) + r'\b', cit_data['passage_text'], re.IGNORECASE) for ec in q_tokens)
            
            if is_referenced or has_error_code:
                final_citations.append(cit_data)

        # Fallback if no specific citation was singled out
        if not final_citations:
            final_citations = list(citations_map.values())[:2]

        citations = final_citations

    return {
        'answer': answer_text,
        'status': status,
        'citations': citations
    }
