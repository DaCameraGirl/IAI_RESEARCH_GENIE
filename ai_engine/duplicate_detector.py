"""
Duplicate Detector - Detect duplicate candidates across studies
Prevents submitting the same prior art to multiple studies
"""

from typing import List, Dict, Set, Optional, Tuple
from pathlib import Path
import hashlib
import json
from datetime import datetime
from difflib import SequenceMatcher
import re


class DuplicateDetector:
    """
    Detect duplicate candidates across studies
    Features:
    - Exact match detection (URL, DOI, patent number)
    - Fuzzy title matching
    - Content similarity detection
    - Cross-study duplicate tracking
    - Deduplication recommendations
    """
    
    def __init__(
        self,
        workspace_root: Optional[Path] = None,
        title_similarity_threshold: float = 0.85,
        content_similarity_threshold: float = 0.90
    ):
        """
        Initialize duplicate detector
        
        Args:
            workspace_root: Root directory of workspace
            title_similarity_threshold: Minimum similarity for title match (0-1)
            content_similarity_threshold: Minimum similarity for content match (0-1)
        """
        if workspace_root is None:
            workspace_root = Path.cwd()
        self.workspace_root = Path(workspace_root)

        self.title_threshold = title_similarity_threshold
        self.content_threshold = content_similarity_threshold
        
        # Duplicate tracking database
        self.db_path = self.workspace_root / ".bob" / "tmp" / "duplicates.json"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Load existing database
        self.duplicate_db = self._load_database()
        
        # Statistics
        self.stats = {
            'candidates_checked': 0,
            'exact_duplicates': 0,
            'fuzzy_duplicates': 0,
            'unique_candidates': 0
        }
    
    def _load_database(self) -> Dict:
        """Load duplicate tracking database"""
        if self.db_path.exists():
            try:
                with open(self.db_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠ Error loading duplicate database: {e}")
        
        return {
            'candidates': {},  # candidate_id -> candidate_info
            'url_index': {},   # url -> [candidate_ids]
            'doi_index': {},   # doi -> [candidate_ids]
            'patent_index': {},  # patent_number -> [candidate_ids]
            'title_index': {},   # normalized_title -> [candidate_ids]
            'last_updated': datetime.now().isoformat()
        }
    
    def load_known_art(self, study_id: str, known_art_rows: List[Dict]):
        """Load known art into tracking index"""
        for row in known_art_rows:
            url = row.get('url')
            if url:
                self.duplicate_db.setdefault('url_index', {}).setdefault(url.lower().strip(), []).append(study_id)
            patent = row.get('patent_number')
            if patent:
                self.duplicate_db.setdefault('patent_index', {}).setdefault(patent.upper().strip(), []).append(study_id)
            doi = row.get('doi')
            if doi:
                self.duplicate_db.setdefault('doi_index', {}).setdefault(doi.lower().strip(), []).append(study_id)

    def _save_database(self):
        """Save duplicate tracking database"""

        self.duplicate_db['last_updated'] = datetime.now().isoformat()
        
        with open(self.db_path, 'w', encoding='utf-8') as f:
            json.dump(self.duplicate_db, f, indent=2)
    
    def check_candidate(
        self,
        candidate: Dict,
        study_id: str
    ) -> Dict:
        """
        Check if candidate is a duplicate
        
        Args:
            candidate: Candidate dict with title, url, doi, etc.
            study_id: Study ID
            
        Returns:
            Duplicate check result
        """
        self.stats['candidates_checked'] += 1
        
        # Generate candidate ID
        candidate_id = self._generate_candidate_id(candidate, study_id)
        
        # Check for exact duplicates
        exact_duplicates = self._find_exact_duplicates(candidate)
        
        if exact_duplicates:
            self.stats['exact_duplicates'] += 1
            return {
                'is_duplicate': True,
                'duplicate_type': 'exact',
                'duplicates': exact_duplicates,
                'recommendation': 'Skip - already submitted to another study'
            }
        
        # Check for fuzzy duplicates
        fuzzy_duplicates = self._find_fuzzy_duplicates(candidate)
        
        if fuzzy_duplicates:
            self.stats['fuzzy_duplicates'] += 1
            return {
                'is_duplicate': True,
                'duplicate_type': 'fuzzy',
                'duplicates': fuzzy_duplicates,
                'recommendation': 'Review - similar to existing candidate'
            }
        
        # Not a duplicate - add to database
        self._add_candidate(candidate_id, candidate, study_id)
        self.stats['unique_candidates'] += 1
        
        return {
            'is_duplicate': False,
            'candidate_id': candidate_id
        }
    
    def _generate_candidate_id(self, candidate: Dict, study_id: str) -> str:
        """Generate unique candidate ID"""
        # Use URL, DOI, or patent number as primary identifier
        identifier = (
            candidate.get('url') or
            candidate.get('doi') or
            candidate.get('patent_number') or
            candidate.get('title', '')
        )
        
        # Hash identifier + study_id
        hash_input = f"{identifier}:{study_id}"
        return hashlib.md5(hash_input.encode()).hexdigest()
    
    def _find_exact_duplicates(self, candidate: Dict) -> List[Dict]:
        """Find exact duplicates by URL, DOI, or patent number"""
        duplicates = []
        
        # Check URL
        url = candidate.get('url')
        if url:
            normalized_url = self._normalize_url(url)
            if normalized_url in self.duplicate_db['url_index']:
                for dup_id in self.duplicate_db['url_index'][normalized_url]:
                    dup_info = self.duplicate_db['candidates'].get(dup_id)
                    if dup_info:
                        duplicates.append({
                            'candidate_id': dup_id,
                            'study_id': dup_info['study_id'],
                            'title': dup_info['title'],
                            'match_type': 'url',
                            'submitted_date': dup_info.get('submitted_date')
                        })
        
        # Check DOI
        doi = candidate.get('doi')
        if doi:
            normalized_doi = self._normalize_doi(doi)
            if normalized_doi in self.duplicate_db['doi_index']:
                for dup_id in self.duplicate_db['doi_index'][normalized_doi]:
                    dup_info = self.duplicate_db['candidates'].get(dup_id)
                    if dup_info:
                        duplicates.append({
                            'candidate_id': dup_id,
                            'study_id': dup_info['study_id'],
                            'title': dup_info['title'],
                            'match_type': 'doi',
                            'submitted_date': dup_info.get('submitted_date')
                        })
        
        # Check patent number
        patent_number = candidate.get('patent_number')
        if patent_number:
            normalized_patent = self._normalize_patent_number(patent_number)
            if normalized_patent in self.duplicate_db['patent_index']:
                for dup_id in self.duplicate_db['patent_index'][normalized_patent]:
                    dup_info = self.duplicate_db['candidates'].get(dup_id)
                    if dup_info:
                        duplicates.append({
                            'candidate_id': dup_id,
                            'study_id': dup_info['study_id'],
                            'title': dup_info['title'],
                            'match_type': 'patent_number',
                            'submitted_date': dup_info.get('submitted_date')
                        })
        
        return duplicates
    
    def _find_fuzzy_duplicates(self, candidate: Dict) -> List[Dict]:
        """Find fuzzy duplicates by title similarity"""
        duplicates = []
        
        title = candidate.get('title', '')
        if not title:
            return duplicates
        
        normalized_title = self._normalize_title(title)
        
        # Check all existing titles
        for existing_title, candidate_ids in self.duplicate_db['title_index'].items():
            similarity = self._calculate_similarity(normalized_title, existing_title)
            
            if similarity >= self.title_threshold:
                for dup_id in candidate_ids:
                    dup_info = self.duplicate_db['candidates'].get(dup_id)
                    if dup_info:
                        duplicates.append({
                            'candidate_id': dup_id,
                            'study_id': dup_info['study_id'],
                            'title': dup_info['title'],
                            'match_type': 'title',
                            'similarity': similarity,
                            'submitted_date': dup_info.get('submitted_date')
                        })
        
        return duplicates
    
    def _add_candidate(self, candidate_id: str, candidate: Dict, study_id: str):
        """Add candidate to database"""
        # Store candidate info
        self.duplicate_db['candidates'][candidate_id] = {
            'study_id': study_id,
            'title': candidate.get('title', ''),
            'url': candidate.get('url'),
            'doi': candidate.get('doi'),
            'patent_number': candidate.get('patent_number'),
            'added_date': datetime.now().isoformat()
        }
        
        # Index by URL
        url = candidate.get('url')
        if url:
            normalized_url = self._normalize_url(url)
            if normalized_url not in self.duplicate_db['url_index']:
                self.duplicate_db['url_index'][normalized_url] = []
            self.duplicate_db['url_index'][normalized_url].append(candidate_id)
        
        # Index by DOI
        doi = candidate.get('doi')
        if doi:
            normalized_doi = self._normalize_doi(doi)
            if normalized_doi not in self.duplicate_db['doi_index']:
                self.duplicate_db['doi_index'][normalized_doi] = []
            self.duplicate_db['doi_index'][normalized_doi].append(candidate_id)
        
        # Index by patent number
        patent_number = candidate.get('patent_number')
        if patent_number:
            normalized_patent = self._normalize_patent_number(patent_number)
            if normalized_patent not in self.duplicate_db['patent_index']:
                self.duplicate_db['patent_index'][normalized_patent] = []
            self.duplicate_db['patent_index'][normalized_patent].append(candidate_id)
        
        # Index by title
        title = candidate.get('title', '')
        if title:
            normalized_title = self._normalize_title(title)
            if normalized_title not in self.duplicate_db['title_index']:
                self.duplicate_db['title_index'][normalized_title] = []
            self.duplicate_db['title_index'][normalized_title].append(candidate_id)
        
        # Save database
        self._save_database()
    
    def _normalize_url(self, url: str) -> str:
        """Normalize URL for comparison"""
        # Remove protocol, www, trailing slash
        url = url.lower()
        url = re.sub(r'^https?://', '', url)
        url = re.sub(r'^www\.', '', url)
        url = url.rstrip('/')
        return url
    
    def _normalize_doi(self, doi: str) -> str:
        """Normalize DOI for comparison"""
        # Remove doi: prefix, lowercase
        doi = doi.lower()
        doi = re.sub(r'^doi:', '', doi)
        doi = doi.strip()
        return doi
    
    def _normalize_patent_number(self, patent_number: str) -> str:
        """Normalize patent number for comparison"""
        # Remove spaces, uppercase
        patent_number = patent_number.upper()
        patent_number = re.sub(r'\s+', '', patent_number)
        return patent_number
    
    def _normalize_title(self, title: str) -> str:
        """Normalize title for comparison"""
        # Lowercase, remove punctuation, extra spaces
        title = title.lower()
        title = re.sub(r'[^\w\s]', ' ', title)
        title = re.sub(r'\s+', ' ', title)
        title = title.strip()
        return title
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate similarity between two texts"""
        return SequenceMatcher(None, text1, text2).ratio()
    
    def get_duplicate_report(self) -> Dict:
        """Generate duplicate detection report"""
        # Count duplicates by study
        study_counts = {}
        for candidate_info in self.duplicate_db['candidates'].values():
            study_id = candidate_info['study_id']
            study_counts[study_id] = study_counts.get(study_id, 0) + 1
        
        return {
            'total_candidates': len(self.duplicate_db['candidates']),
            'candidates_by_study': study_counts,
            'statistics': self.stats,
            'last_updated': self.duplicate_db['last_updated']
        }
    
    def clear_study_candidates(self, study_id: str):
        """Remove all candidates for a study (e.g., after submission)"""
        # Find candidates for study
        candidates_to_remove = [
            cid for cid, info in self.duplicate_db['candidates'].items()
            if info['study_id'] == study_id
        ]
        
        # Remove from database
        for candidate_id in candidates_to_remove:
            candidate_info = self.duplicate_db['candidates'][candidate_id]
            
            # Remove from indexes
            url = candidate_info.get('url')
            if url:
                normalized_url = self._normalize_url(url)
                if normalized_url in self.duplicate_db['url_index']:
                    self.duplicate_db['url_index'][normalized_url].remove(candidate_id)
            
            doi = candidate_info.get('doi')
            if doi:
                normalized_doi = self._normalize_doi(doi)
                if normalized_doi in self.duplicate_db['doi_index']:
                    self.duplicate_db['doi_index'][normalized_doi].remove(candidate_id)
            
            patent_number = candidate_info.get('patent_number')
            if patent_number:
                normalized_patent = self._normalize_patent_number(patent_number)
                if normalized_patent in self.duplicate_db['patent_index']:
                    self.duplicate_db['patent_index'][normalized_patent].remove(candidate_id)
            
            title = candidate_info.get('title', '')
            if title:
                normalized_title = self._normalize_title(title)
                if normalized_title in self.duplicate_db['title_index']:
                    self.duplicate_db['title_index'][normalized_title].remove(candidate_id)
            
            # Remove candidate
            del self.duplicate_db['candidates'][candidate_id]
        
        # Save database
        self._save_database()
        
        print(f"✓ Removed {len(candidates_to_remove)} candidates for study {study_id}")


# Example usage
if __name__ == "__main__":
    detector = DuplicateDetector(Path("."))
    
    # Example candidates
    candidate1 = {
        'title': 'Blender with Offset Blades',
        'url': 'https://example.com/blender-patent',
        'patent_number': 'US1234567'
    }
    
    candidate2 = {
        'title': 'Blender with Offset Blades',  # Same title
        'url': 'https://example.com/blender-patent',  # Same URL
        'patent_number': 'US1234567'  # Same patent
    }
    
    # Check first candidate
    result1 = detector.check_candidate(candidate1, '26052')
    print(f"Candidate 1: {result1}")
    
    # Check second candidate (should be duplicate)
    result2 = detector.check_candidate(candidate2, '25974')
    print(f"Candidate 2: {result2}")
    
    # Get report
    report = detector.get_duplicate_report()
    print(f"\nDuplicate Report:")
    print(f"  Total candidates: {report['total_candidates']}")
    print(f"  By study: {report['candidates_by_study']}")