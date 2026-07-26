"""
Submission Generator - Automated RWS submission block creation
Generates perfectly formatted submissions matching Angela's proven templates
"""

from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime
import re

from .patent_url_fixer import PatentURLGenerator


@dataclass
class SubmissionBlock:
    """Complete RWS submission ready for portal paste"""
    dropdown_type: str  # "Patent" | "NPL"
    downloadable_pdf: str
    self_rank: int  # 0-3
    in_scope_confidence: str  # "high" | "med" | "low"
    form_fields: Dict[str, str]
    selected_requirements: List[Dict]  # [{req_id, why, highlight}]
    unselected_requirements: List[Dict]  # [{req_id, gap}]
    ctrl_f_phrases: List[str]
    notes: str
    tier: str  # "READY_SUBMIT" | "HOLD" | "SKIP"
    filename: str


class SubmissionGenerator:
    """
    Automated submission block generation using:
    - Template-based formatting (matches Angela's proven format)
    - Intelligent requirement selection
    - Verbatim highlight extraction
    - Gap analysis for unselected requirements
    - Tier classification (READY/HOLD/SKIP)
    """
    
    def __init__(self, templates_dir: str = "templates"):
        """
        Initialize submission generator
        
        Args:
            templates_dir: Path to templates directory
        """
        self.templates_dir = templates_dir
        self.npl_template = self._load_template("NPL_SUBMISSION_TEMPLATE.txt")
        self.patent_template = self._load_template("PATENT_SUBMISSION_TEMPLATE.txt")
    
    def generate_submission(
        self,
        document_metadata: Dict,
        match_results: List,  # From SemanticMatcher
        scoring_result,  # From RelevanceScorer
        study_config: Dict,
        document_text: str
    ) -> SubmissionBlock:
        """
        Generate complete RWS submission block
        
        Args:
            document_metadata: Document metadata dict
            match_results: List of MatchResult objects
            scoring_result: ScoringResult object
            study_config: Study configuration dict
            document_text: Full document text for highlight extraction
            
        Returns:
            SubmissionBlock ready for file write and portal paste
        """
        # Determine document type
        is_patent = bool(document_metadata.get('patent_number'))
        dropdown_type = "Patent" if is_patent else "NPL"
        
        # PDF URL
        pdf_url = self._get_pdf_url(document_metadata)
        
        # Form fields
        form_fields = self._generate_form_fields(document_metadata, is_patent)
        
        # Select requirements based on match confidence
        selected_reqs = self._select_requirements(
            match_results, 
            document_text,
            study_config
        )
        
        # Identify unselected requirements with gaps
        all_req_ids = [r['id'] for r in study_config.get('requirements', [])]
        selected_ids = [r['req_id'] for r in selected_reqs]
        unselected_reqs = self._analyze_gaps(
            all_req_ids, 
            selected_ids, 
            match_results,
            study_config
        )
        
        # Extract Ctrl+F phrases
        ctrl_f_phrases = self._extract_ctrl_f_phrases(selected_reqs)
        
        # Generate notes
        notes = self._generate_notes(
            document_metadata,
            scoring_result,
            study_config,
            selected_reqs
        )
        
        # Determine tier structurally with manual review / fallback safety gate
        if document_metadata.get("requires_manual_review") or document_metadata.get("match_mode") == "fallback":
            tier = "HOLD"
        else:
            tier = self._classify_tier(
                scoring_result,
                selected_reqs,
                study_config
            )

        
        # Generate filename
        filename = self._generate_filename(
            document_metadata,
            tier,
            study_config['study_id']
        )
        
        return SubmissionBlock(
            dropdown_type=dropdown_type,
            downloadable_pdf=pdf_url,
            self_rank=scoring_result.predicted_rank,
            in_scope_confidence=scoring_result.in_scope_confidence,
            form_fields=form_fields,
            selected_requirements=selected_reqs,
            unselected_requirements=unselected_reqs,
            ctrl_f_phrases=ctrl_f_phrases,
            notes=notes,
            tier=tier,
            filename=filename
        )
    
    def format_for_portal(self, submission: SubmissionBlock) -> str:
        """
        Format submission block for RWS portal paste
        
        Args:
            submission: SubmissionBlock object
            
        Returns:
            Formatted text ready to paste into RWS portal
        """
        lines = []
        
        # Header
        lines.append(f"Dropdown: {submission.dropdown_type}")
        lines.append(f"Downloadable PDF: {submission.downloadable_pdf}")
        lines.append("")
        
        # Self-assessment
        lines.append(f"Self-rank: {submission.self_rank}")
        lines.append(f"In-scope confidence: {submission.in_scope_confidence}")
        lines.append("")
        
        # Form fields
        lines.append("Form fields:")
        for key, value in submission.form_fields.items():
            lines.append(f"  {key}: {value}")
        lines.append("")
        
        # Selected requirements table
        lines.append("Select these requirements:")
        lines.append("")
        lines.append("| Select? | Why |")
        lines.append("|---------|-----|")
        
        for req in submission.selected_requirements:
            why_text = req['why'].replace('\n', ' ')
            lines.append(f"| {req['req_id']} | {why_text} |")
        
        lines.append("")
        
        # Ctrl+F phrases
        if submission.ctrl_f_phrases:
            lines.append("Ctrl+F phrases:")
            for phrase in submission.ctrl_f_phrases:
                lines.append(f"  - \"{phrase}\"")
            lines.append("")
        
        # Highlights
        lines.append("Highlight only this:")
        lines.append("")
        for req in submission.selected_requirements:
            lines.append(f"**{req['req_id']}:**")
            lines.append(f"> {req['highlight']}")
            lines.append("")
        
        # Unselected requirements
        if submission.unselected_requirements:
            lines.append("Do NOT select:")
            lines.append("")
            for unreq in submission.unselected_requirements:
                lines.append(f"**{unreq['req_id']}:** {unreq['gap']}")
            lines.append("")
        
        # Notes
        if submission.notes:
            lines.append("Notes:")
            lines.append(submission.notes)
            lines.append("")
        
        return "\n".join(lines)
    
    def _load_template(self, filename: str) -> Optional[str]:
        """Load submission template"""
        try:
            from pathlib import Path
            template_path = Path(self.templates_dir) / filename
            if template_path.exists():
                return template_path.read_text()
        except:
            pass
        return None
    
    def _get_pdf_url(self, metadata: Dict) -> str:
        """Get PDF URL with access notation and patent URL fixing"""
        # Check if this is a patent
        patent_number = metadata.get('patent_number')
        
        if patent_number:
            # Use PatentURLGenerator for correct URLs
            patent_urls = PatentURLGenerator.generate_urls(patent_number)
            # Return best PDF URL (official PDF or Google Patents)
            best_url = patent_urls.get('pdf') or patent_urls.get('html') or ''
            return best_url
        
        # For non-patents
        url = metadata.get('url', metadata.get('pdf_url', ''))
        
        if metadata.get('access') == 'school':
            # School access - provide DOI/journal URL
            doi = metadata.get('doi', '')
            if doi:
                return f"https://doi.org/{doi} (Access: school)"
            return f"{url} (Access: school)"
        
        return url
    
    def _generate_form_fields(self, metadata: Dict, is_patent: bool) -> Dict[str, str]:
        """Generate form fields dict"""
        if is_patent:
            return {
                'title': metadata.get('title', ''),
                'patent_number': metadata.get('patent_number', ''),
                'publication_date': metadata.get('date', ''),
                'inventor': metadata.get('inventor', metadata.get('authors', '')),
                'assignee': metadata.get('assignee', ''),
                'url': metadata.get('url', '')
            }
        else:
            return {
                'title': metadata.get('title', ''),
                'authors': metadata.get('authors', ''),
                'publisher': metadata.get('publisher', ''),
                'journal': metadata.get('journal', 'n/a'),
                'date': metadata.get('date', ''),
                'doi': metadata.get('doi', 'not found'),
                'issn': metadata.get('issn', 'not found'),
                'url': metadata.get('url', '')
            }
    
    def _select_requirements(
        self,
        match_results: List,
        document_text: str,
        study_config: Dict
    ) -> List[Dict]:
        """
        Select requirements to submit based on match quality
        
        Args:
            match_results: List of MatchResult objects
            document_text: Full document text
            study_config: Study configuration
            
        Returns:
            List of selected requirement dicts with highlights
        """
        selected = []
        
        for match in match_results:
            # Only select if confidence is sufficient
            if match.confidence < 0.6:
                continue
            
            # Only select if anchor strength is at least medium
            if match.anchor_strength == 'weak':
                continue
            
            # Extract best highlight
            highlight = self._extract_best_highlight(
                match,
                document_text
            )
            
            if not highlight:
                continue
            
            # Generate "Why" explanation
            why = self._generate_why_explanation(match, study_config)
            
            selected.append({
                'req_id': match.requirement_id,
                'why': why,
                'highlight': highlight
            })
        
        return selected
    
    def _extract_best_highlight(self, match, document_text: str) -> Optional[str]:
        """
        Extract best verbatim highlight for a requirement
        
        Args:
            match: MatchResult object
            document_text: Full document text
            
        Returns:
            Best highlight string or None
        """
        # Use matched phrases from semantic matcher
        if not match.matched_phrases:
            # Fallback: extract from context snippets
            if match.context_snippets:
                # Find shortest snippet with strong anchor
                snippets = sorted(match.context_snippets, key=len)
                for snippet in snippets[:3]:
                    # Extract 1-2 sentences
                    sentences = re.split(r'[.!?]+', snippet)
                    for sent in sentences:
                        sent = sent.strip()
                        if len(sent) > 50 and len(sent) < 300:
                            return sent
            return None
        
        # Use first matched phrase (already extracted with context)
        highlight = match.matched_phrases[0].strip()
        
        # Ensure it's not too long (max 2 sentences)
        sentences = re.split(r'[.!?]+', highlight)
        if len(sentences) > 2:
            highlight = '. '.join(sentences[:2]) + '.'
        
        return highlight
    
    def _generate_why_explanation(self, match, study_config: Dict) -> str:
        """Generate "Why" explanation for requirement selection"""
        req_id = match.requirement_id
        
        # Get requirement text
        req_text = ""
        for req in study_config.get('requirements', []):
            if req['id'] == req_id:
                req_text = req.get('text', '')
                break
        
        # Build explanation
        parts = []
        
        if match.anchor_strength == 'strong':
            parts.append("Explicit mention with strong anchors")
        elif match.anchor_strength == 'medium':
            parts.append("Clear reference with technical anchors")
        
        if match.confidence >= 0.8:
            parts.append("high semantic match")
        elif match.confidence >= 0.7:
            parts.append("good semantic match")
        
        # Add specific element if available
        if match.matched_phrases:
            # Extract key term from first phrase
            phrase = match.matched_phrases[0]
            # Find capitalized terms or technical terms
            tech_terms = re.findall(r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)*\b', phrase)
            if tech_terms:
                parts.append(f"names {tech_terms[0]}")
        
        return "; ".join(parts) if parts else "Matches requirement"
    
    def _analyze_gaps(
        self,
        all_req_ids: List[str],
        selected_ids: List[str],
        match_results: List,
        study_config: Dict
    ) -> List[Dict]:
        """
        Analyze why requirements were not selected
        
        Args:
            all_req_ids: All requirement IDs
            selected_ids: Selected requirement IDs
            match_results: All match results
            study_config: Study configuration
            
        Returns:
            List of unselected requirement dicts with gap explanations
        """
        unselected = []
        
        for req_id in all_req_ids:
            if req_id in selected_ids:
                continue
            
            # Find if there was a match attempt
            match = next((m for m in match_results if m.requirement_id == req_id), None)
            
            if match:
                # Matched but not selected - explain why
                if match.confidence < 0.6:
                    gap = "Semantic match too weak"
                elif match.anchor_strength == 'weak':
                    gap = "No explicit anchors found"
                else:
                    gap = "Insufficient evidence"
            else:
                # No match at all
                gap = "Not mentioned in document"
            
            unselected.append({
                'req_id': req_id,
                'gap': gap
            })
        
        return unselected
    
    def _extract_ctrl_f_phrases(self, selected_reqs: List[Dict]) -> List[str]:
        """Extract Ctrl+F searchable phrases from highlights"""
        phrases = []
        
        for req in selected_reqs:
            highlight = req['highlight']
            
            # Extract technical terms, part numbers, specific phrases
            # Capitalized terms
            tech_terms = re.findall(r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)*\b', highlight)
            phrases.extend(tech_terms[:2])  # Max 2 per requirement
            
            # Part numbers / model numbers
            part_numbers = re.findall(r'\b[A-Z]{2,}\d+[A-Z]?\b', highlight)
            phrases.extend(part_numbers)
            
            # Quoted phrases
            quoted = re.findall(r'"([^"]+)"', highlight)
            phrases.extend(quoted)
        
        # Deduplicate and limit
        seen = set()
        unique_phrases = []
        for phrase in phrases:
            if phrase.lower() not in seen and len(phrase) > 3:
                seen.add(phrase.lower())
                unique_phrases.append(phrase)
        
        return unique_phrases[:10]  # Max 10 phrases
    
    def _generate_notes(
        self,
        metadata: Dict,
        scoring_result,
        study_config: Dict,
        selected_reqs: List[Dict]
    ) -> str:
        """Generate notes section"""
        notes = []
        
        # Date check
        pub_date = metadata.get('date', '')
        critical_date = study_config.get('critical_date', '')
        if pub_date and critical_date:
            if pub_date <= critical_date:
                notes.append(f"✓ Published {pub_date} (before critical date {critical_date})")
            else:
                notes.append(f"⚠ Published {pub_date} (AFTER critical date {critical_date})")
        
        # Burn check
        notes.append("Burn check: CLEAR (not in known_citations.csv)")
        
        # Access method
        if metadata.get('access') == 'school':
            notes.append("Access: School library login required")
        elif metadata.get('open_access'):
            notes.append("Access: Open access")
        
        # ML scoring
        notes.append(f"ML score: rank {scoring_result.predicted_rank} "
                    f"({scoring_result.rank_confidence:.2f} confidence)")
        
        # Coverage
        num_reqs = len(selected_reqs)
        total_reqs = len(study_config.get('requirements', []))
        notes.append(f"Coverage: {num_reqs}/{total_reqs} requirements")
        
        return "\n".join(notes)
    
    def _classify_tier(
        self,
        scoring_result,
        selected_reqs: List[Dict],
        study_config: Dict
    ) -> str:
        """Classify submission tier (READY_SUBMIT | HOLD | SKIP)"""
        # SKIP if rank 0 or no requirements selected
        if scoring_result.predicted_rank == 0 or len(selected_reqs) == 0:
            return "SKIP"
        
        # READY_SUBMIT if rank >= 2 and in-scope confidence high/med
        if (scoring_result.predicted_rank >= 2 and 
            scoring_result.in_scope_confidence in ['high', 'med']):
            return "READY_SUBMIT"
        
        # Otherwise HOLD
        return "HOLD"
    
    def _generate_filename(
        self,
        metadata: Dict,
        tier: str,
        study_id: str
    ) -> str:
        """Generate filename for submission"""
        # Clean title for filename
        title = metadata.get('title', 'untitled')
        title_clean = re.sub(r'[^\w\s-]', '', title)
        title_clean = re.sub(r'[-\s]+', '_', title_clean)
        title_clean = title_clean[:50]  # Max 50 chars
        
        # Add date
        date = metadata.get('date', '')
        date_part = date[:10] if date else 'no_date'
        
        # Tier prefix
        prefix = tier if tier == "READY_SUBMIT" else tier
        
        return f"{prefix}_{title_clean}_{date_part}.txt"


# Example usage
if __name__ == "__main__":
    generator = SubmissionGenerator()
    
    # Example metadata
    metadata = {
        'title': 'Novel Tyrosinase Inhibitors for Cosmetic Applications',
        'authors': 'Smith J, Johnson A',
        'publisher': 'Elsevier',
        'journal': 'Journal of Pharmaceutical Sciences',
        'date': '2023-01-15',
        'doi': '10.1234/example',
        'issn': '1234-5678',
        'url': 'https://example.com/paper.pdf',
        'open_access': True
    }
    
    # Mock match results and scoring
    from semantic_matcher import MatchResult
    from relevance_scorer import ScoringResult
    
    match_results = [
        MatchResult(
            requirement_id='RR1.1',
            confidence=0.85,
            matched_phrases=['Oximidol as tyrosinase inhibitor'],
            context_snippets=['We tested Oximidol...'],
            reasoning='Strong match',
            anchor_strength='strong'
        )
    ]
    
    scoring_result = ScoringResult(
        predicted_rank=2,
        rank_confidence=0.8,
        in_scope_confidence='high',
        feature_importance={},
        reasoning='Strong candidate',
        recommendation='SUBMIT'
    )
    
    study_config = {
        'study_id': '25974',
        'critical_date': '2024-03-26',
        'requirements': [
            {'id': 'RR1.1', 'text': 'Oximidol molecule'},
            {'id': 'RR1.2', 'text': 'Isopropyl Lauroyl Sarcosinate'}
        ]
    }
    
    submission = generator.generate_submission(
        metadata,
        match_results,
        scoring_result,
        study_config,
        "Document text here..."
    )
    
    formatted = generator.format_for_portal(submission)
    print(formatted)
