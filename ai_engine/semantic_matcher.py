"""
Semantic Matcher - AI-powered requirement matching using embeddings
Replaces keyword-only search with intelligent semantic understanding
"""

import numpy as np
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
import re


@dataclass
class Requirement:
    """Study requirement with semantic understanding"""
    id: str
    text: str
    must_show_elements: List[str]
    keywords: List[str]
    embedding: Optional[np.ndarray] = None
    priority: int = 1  # 1=critical, 2=important, 3=nice-to-have
    # Co-occurrence groups: each inner list is OR'd, groups are AND'd.
    # e.g. [["thiamidol", "oximidol"], ["isopropyl lauroyl sarcosinate", "eldew sl-205"]]
    # means: (thiamidol OR oximidol) AND (ILS OR Eldew SL-205) must both appear.
    must_cooccur_groups: Optional[List[List[str]]] = None


@dataclass
class MatchResult:
    """Semantic match result with confidence scoring"""
    requirement_id: str
    confidence: float  # 0.0-1.0
    matched_phrases: List[str]
    context_snippets: List[str]
    reasoning: str
    anchor_strength: str  # "strong" | "medium" | "weak"


class SemanticMatcher:
    """
    Intelligent requirement matching using:
    - Sentence embeddings for semantic similarity
    - Named entity recognition for anchor detection
    - Context-aware phrase extraction
    - Multi-level confidence scoring
    """
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        """
        Initialize semantic matcher
        
        Args:
            model_name: Sentence transformer model for embeddings
        """
        self.model_name = model_name
        self.model = None  # Lazy load
        self.fallback_mode = False
        self.requirements_cache: Dict[str, List[Requirement]] = {}
        
    def _lazy_load_model(self):
        """Load sentence transformer model on first use"""
        if self.model is None and not self.fallback_mode:
            try:
                from sentence_transformers import SentenceTransformer
                self.model = SentenceTransformer(self.model_name)
            except ImportError:
                self.fallback_mode = True
    
    def load_requirements(self, study_id: str, requirements: List[Dict]) -> List[Requirement]:
        """
        Load and embed study requirements
        
        Args:
            study_id: Study identifier (e.g., "25974")
            requirements: List of requirement dicts with id, text, elements, keywords
            
        Returns:
            List of Requirement objects with embeddings
        """
        self._lazy_load_model()
        
        req_objects = []
        for req in requirements:
            req_obj = Requirement(
                id=req['id'],
                text=req.get('text', req.get('name', '')),
                must_show_elements=req.get('must_show_elements', []),
                keywords=req.get('keywords', []),
                priority=req.get('priority', 1),
                must_cooccur_groups=req.get('must_cooccur_groups')
            )
            
            if not self.fallback_mode and self.model is not None:
                req_obj.embedding = self.model.encode(req_obj.text, convert_to_numpy=True)
            req_objects.append(req_obj)
        
        self.requirements_cache[study_id] = req_objects
        return req_objects
    
    def match_document(
        self, 
        study_id: str,
        document_text: str,
        document_metadata: Dict,
        min_confidence: float = 0.6
    ) -> List[MatchResult]:
        """
        Match document against study requirements using semantic analysis
        
        Args:
            study_id: Study identifier
            document_text: Full text of candidate document
            document_metadata: Dict with title, authors, date, etc.
            min_confidence: Minimum confidence threshold (0.0-1.0)
            
        Returns:
            List of MatchResult objects for requirements that match
        """
        if study_id not in self.requirements_cache or not self.requirements_cache[study_id]:
            return [MatchResult(
                requirement_id="REQ-FALLBACK",
                confidence=0.50,
                matched_phrases=[document_metadata.get('title', 'Prior Art Candidate')],
                context_snippets=[document_text[:300]],
                reasoning="Fallback discovery - unverified requirement match; requires manual review.",
                anchor_strength="weak"
            )]

        
        self._lazy_load_model()
        requirements = self.requirements_cache[study_id]

        
        # Split document into semantic chunks (paragraphs/sections)
        chunks = self._chunk_document(document_text)
        chunk_embeddings = None
        if not self.fallback_mode and self.model is not None:
            chunk_embeddings = self.model.encode(chunks, convert_to_numpy=True)
        
        matches = []
        
        for req in requirements:
            # Calculate semantic similarity between requirement and all chunks
            if chunk_embeddings is not None and req.embedding is not None:
                similarities = np.dot(chunk_embeddings, req.embedding)
            else:
                similarities = np.array(
                    [
                        self._fallback_similarity(
                            req.text,
                            chunk,
                            req.must_show_elements + req.keywords,
                        )
                        for chunk in chunks
                    ],
                    dtype=float,
                )
            
            # Find top matching chunks
            top_indices = np.argsort(similarities)[-3:][::-1]  # Top 3 chunks
            top_chunks = [chunks[i] for i in top_indices]
            top_scores = [similarities[i] for i in top_indices]
            
            # Check for explicit keyword/element matches (anchor strength)
            # must_show_elements are HARD requirements — ALL must be present
            anchor_matches = self._find_anchor_matches(
                top_chunks,
                keywords=req.keywords,
                must_show_elements=req.must_show_elements,
                must_cooccur_groups=getattr(req, 'must_cooccur_groups', None)
            )
            # Hard fail: if any must_show_element is missing, skip this requirement entirely
            if anchor_matches.get('must_show_failed'):
                continue
            
            # Calculate overall confidence
            confidence = self._calculate_confidence(
                semantic_scores=top_scores,
                anchor_matches=anchor_matches,
                requirement=req,
                document_metadata=document_metadata
            )
            
            if confidence >= min_confidence:
                match = MatchResult(
                    requirement_id=req.id,
                    confidence=confidence,
                    matched_phrases=anchor_matches['phrases'],
                    context_snippets=top_chunks,
                    reasoning=self._generate_reasoning(
                        req, top_chunks, anchor_matches, confidence
                    ),
                    anchor_strength=anchor_matches['strength']
                )
                matches.append(match)
        
        # Sort by confidence (highest first)
        matches.sort(key=lambda x: x.confidence, reverse=True)
        return matches

    def _normalize_tokens(self, text: str) -> List[str]:
        return re.findall(r"[a-z0-9][a-z0-9'()/\-]{2,}", text.lower())

    def _fallback_similarity(
        self,
        requirement_text: str,
        chunk_text: str,
        anchors: List[str],
    ) -> float:
        """Cheap semantic-ish fallback when embedding model is unavailable."""
        req_tokens = set(self._normalize_tokens(requirement_text))
        chunk_tokens = set(self._normalize_tokens(chunk_text))
        if not req_tokens or not chunk_tokens:
            return 0.0

        overlap = len(req_tokens & chunk_tokens) / max(1, len(req_tokens))
        anchor_hits = sum(1 for anchor in anchors if anchor and anchor.lower() in chunk_text.lower())
        anchor_bonus = min(0.35, anchor_hits * 0.08)

        phrase_bonus = 0.0
        for phrase in re.findall(r"[A-Za-z0-9'()/\-]+(?:\s+[A-Za-z0-9'()/\-]+){1,4}", requirement_text):
            phrase = phrase.strip()
            if len(phrase) >= 12 and phrase.lower() in chunk_text.lower():
                phrase_bonus = max(phrase_bonus, 0.15)

        return min(1.0, overlap + anchor_bonus + phrase_bonus)
    
    def _chunk_document(self, text: str, chunk_size: int = 500) -> List[str]:
        """
        Split document into semantic chunks
        
        Args:
            text: Full document text
            chunk_size: Target characters per chunk
            
        Returns:
            List of text chunks
        """
        # Split on paragraph boundaries first
        paragraphs = text.split('\n\n')
        
        chunks = []
        current_chunk = ""
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
                
            if len(current_chunk) + len(para) < chunk_size:
                current_chunk += para + "\n\n"
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = para + "\n\n"
        
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        return chunks if chunks else [text]
    
    def _find_anchor_matches(
        self, 
        chunks: List[str], 
        keywords: List[str],
        must_show_elements: Optional[List[str]] = None,
        must_cooccur_groups: Optional[List[List[str]]] = None
    ) -> Dict:
        """
        Find explicit anchor matches (named entities, technical terms)
        
        must_show_elements: HARD requirements — ALL must be present in the text,
        otherwise anchor_strength="fail" and must_show_failed=True is returned.
        
        must_cooccur_groups: List of OR-groups, ALL groups must match ≥1 term.
        e.g. [["thiamidol", "oximidol"], ["isopropyl lauroyl sarcosinate", "eldew sl-205"]]
        means (thiamidol OR oximidol) AND (ILS OR Eldew) must both appear.
        
        Keywords are OR'd as before (for scoring/ranking).
        
        Args:
            chunks: Text chunks to search
            keywords: List of anchor terms/phrases to find (OR logic)
            must_show_elements: List of terms that MUST ALL be present (AND logic)
            must_cooccur_groups: List of OR-groups, ALL groups must match
            
        Returns:
            Dict with matched_phrases, count, strength, must_show_failed
        """
        matched_phrases = []
        match_count = 0
        
        full_text = " ".join(chunks).lower()
        
        # HARD GATE 1: check must_show_elements — ALL must be present
        must_show_elements = must_show_elements or []
        missing_required = []
        for required in must_show_elements:
            if required.lower() not in full_text:
                missing_required.append(required)
        
        if missing_required:
            # Hard fail — required element(s) missing, do not score this document
            return {
                'phrases': [],
                'count': 0,
                'strength': 'fail',
                'must_show_failed': True,
                'missing_required': missing_required
            }
        
        # HARD GATE 2: check must_cooccur_groups — EACH group must have ≥1 match
        # e.g. [["thiamidol", "oximidol"], ["isopropyl lauroyl sarcosinate", "eldew sl-205"]]
        # → group 0 must match AND group 1 must match
        must_cooccur_groups = must_cooccur_groups or []
        failed_groups = []
        cooccur_hits = []
        for group_idx, group in enumerate(must_cooccur_groups):
            group_matched = False
            group_hit = None
            for term in group:
                if term.lower() in full_text:
                    group_matched = True
                    group_hit = term
                    # Extract context
                    pattern = re.compile(r'(.{0,50}' + re.escape(term) + r'.{0,50})', re.IGNORECASE)
                    matches = pattern.findall(full_text)
                    if matches:
                        matched_phrases.extend(matches[:1])
                    break
            if not group_matched:
                failed_groups.append(group_idx)
            elif group_hit:
                cooccur_hits.append(group_hit)
        
        if failed_groups:
            return {
                'phrases': [],
                'count': 0,
                'strength': 'fail',
                'must_show_failed': True,
                'missing_cooccur_groups': failed_groups
            }
        
        # Count co-occur hits toward match_count for scoring
        match_count += len(cooccur_hits)
        
        # OR matching for keywords (existing behavior, for scoring/ranking)
        for anchor in keywords:
            # Try exact match first
            if anchor.lower() in full_text:
                # Extract context around match
                pattern = re.compile(
                    r'(.{0,50}' + re.escape(anchor) + r'.{0,50})',
                    re.IGNORECASE
                )
                matches = pattern.findall(full_text)
                if matches:
                    matched_phrases.extend(matches[:2])  # Max 2 per anchor
                    match_count += 1
        
        # Assess anchor strength
        # If we have must_show_elements, they already matched (hard gate above),
        # so count them toward strength scoring
        total_anchors = match_count + len(must_show_elements)
        if total_anchors >= 3:
            strength = "strong"
        elif total_anchors >= 1:
            strength = "medium"
        else:
            strength = "weak"
        
        return {
            'phrases': matched_phrases,
            'count': match_count,
            'strength': strength,
            'must_show_failed': False
        }
    
    def _calculate_confidence(
        self,
        semantic_scores: List[float],
        anchor_matches: Dict,
        requirement: Requirement,
        document_metadata: Dict
    ) -> float:
        """
        Calculate overall match confidence using multiple signals
        
        Args:
            semantic_scores: Similarity scores from embeddings
            anchor_matches: Explicit anchor match results
            requirement: Requirement object
            document_metadata: Document metadata dict
            
        Returns:
            Confidence score 0.0-1.0
        """
        # Base semantic similarity (top chunk)
        semantic_conf = float(semantic_scores[0]) if semantic_scores else 0.0
        
        # Anchor strength bonus
        anchor_bonus = {
            'strong': 0.3,
            'medium': 0.15,
            'weak': 0.0
        }[anchor_matches['strength']]
        
        # Priority weighting (critical requirements need higher confidence)
        priority_threshold = {
            1: 0.0,   # Critical - no penalty
            2: -0.05, # Important - slight penalty
            3: -0.1   # Nice-to-have - larger penalty
        }[requirement.priority]
        
        # Document quality signals
        quality_bonus = 0.0
        if document_metadata.get('peer_reviewed'):
            quality_bonus += 0.05
        if document_metadata.get('doi'):
            quality_bonus += 0.03
        
        # Combine signals
        confidence = min(1.0, max(0.0,
            semantic_conf + anchor_bonus + priority_threshold + quality_bonus
        ))
        
        return confidence
    
    def _generate_reasoning(
        self,
        requirement: Requirement,
        chunks: List[str],
        anchor_matches: Dict,
        confidence: float
    ) -> str:
        """
        Generate human-readable reasoning for the match
        
        Args:
            requirement: Requirement object
            chunks: Matched text chunks
            anchor_matches: Anchor match results
            confidence: Overall confidence score
            
        Returns:
            Reasoning string
        """
        reasoning_parts = []
        
        # Semantic match
        reasoning_parts.append(
            f"Semantic similarity: {confidence:.2f} confidence"
        )
        
        # Anchor matches
        if anchor_matches['count'] > 0:
            reasoning_parts.append(
                f"Found {anchor_matches['count']} explicit anchor(s): "
                f"{anchor_matches['strength']} match strength"
            )
        else:
            reasoning_parts.append("No explicit anchors found (semantic match only)")
        
        # Context preview
        if chunks:
            preview = chunks[0][:150] + "..." if len(chunks[0]) > 150 else chunks[0]
            reasoning_parts.append(f"Context: {preview}")
        
        return " | ".join(reasoning_parts)
    
    def batch_match_documents(
        self,
        study_id: str,
        documents: List[Tuple[str, Dict]],
        min_confidence: float = 0.6,
        max_workers: int = 4
    ) -> Dict[str, List[MatchResult]]:
        """
        Match multiple documents in parallel
        
        Args:
            study_id: Study identifier
            documents: List of (text, metadata) tuples
            min_confidence: Minimum confidence threshold
            max_workers: Number of parallel workers
            
        Returns:
            Dict mapping document ID to list of matches
        """
        from concurrent.futures import ThreadPoolExecutor
        
        results = {}
        
        def process_doc(doc_tuple):
            text, metadata = doc_tuple
            doc_id = metadata.get('id', metadata.get('title', 'unknown'))
            matches = self.match_document(study_id, text, metadata, min_confidence)
            return doc_id, matches
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for doc_id, matches in executor.map(process_doc, documents):
                results[doc_id] = matches
        
        return results


# Example usage
if __name__ == "__main__":
    # Initialize matcher
    matcher = SemanticMatcher()
    
    # Load requirements for a study
    requirements = [
        {
            'id': 'RR1.1',
            'text': 'Oximidol molecule with specific chemical structure',
            'must_show_elements': ['Oximidol', 'tyrosinase inhibitor'],
            'keywords': ['alkylamidothiazole', 'skin whitening', 'melanin'],
            'priority': 1
        },
        {
            'id': 'RR1.2',
            'text': 'Isopropyl Lauroyl Sarcosinate as surfactant',
            'must_show_elements': ['Isopropyl Lauroyl Sarcosinate'],
            'keywords': ['surfactant', 'emulsifier', 'cosmetic'],
            'priority': 1
        }
    ]
    
    matcher.load_requirements("25974", requirements)
    
    # Match a candidate document
    doc_text = """
    This study investigates novel tyrosinase inhibitors for cosmetic applications.
    We tested Oximidol, an alkylamidothiazole derivative, combined with various
    surfactants including Isopropyl Lauroyl Sarcosinate. Results show significant
    melanin reduction in vitro.
    """
    
    metadata = {
        'title': 'Novel Tyrosinase Inhibitors',
        'date': '2023-01-15',
        'doi': '10.1234/example',
        'peer_reviewed': True
    }
    
    matches = matcher.match_document("25974", doc_text, metadata)
    
    for match in matches:
        print(f"\n{match.requirement_id}: {match.confidence:.2f} confidence")
        print(f"Anchor strength: {match.anchor_strength}")
        print(f"Reasoning: {match.reasoning}")
        print(f"Matched phrases: {match.matched_phrases[:2]}")
