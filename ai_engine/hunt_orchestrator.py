"""
Hunt Orchestrator - Automated multi-source prior art hunting
Searches unconventional sources, filters known citations, enforces no-paywall rule
"""

from typing import List, Dict, Optional, Set
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime
import json

from .advanced_search import AdvancedSearchEngine, SearchResult
from .duplicate_detector import DuplicateDetector
from .semantic_matcher import SemanticMatcher
from .relevance_scorer import RelevanceScorer
from .submission_generator import SubmissionGenerator

try:
    from .keyword_expander import KeywordExpander
except ImportError:
    KeywordExpander = None



@dataclass
class HuntConfig:
    """Configuration for automated hunt"""
    study_id: str
    study_folder: Path
    critical_date: str
    keywords: List[str]
    part_numbers: List[str]
    manufacturers: List[str]
    target_domains: List[str]
    patent_number: Optional[str] = None
    
    # Source-specific configs
    enable_wayback: bool = True
    enable_fcc: bool = True
    enable_ptab: bool = True
    enable_usenet: bool = True
    enable_university: bool = True
    enable_distributor: bool = True
    enable_archive_texts: bool = True
    enable_github: bool = True
    enable_forums: bool = True
    
    # Limits
    max_results_per_source: int = 50
    min_confidence: float = 0.6



class HuntOrchestrator:
    """
    Orchestrates automated prior art hunting:
    1. Search all unconventional sources in parallel
    2. Filter known citations (STRICT - nothing from known_citations.csv)
    3. Filter paywalls (STRICT - only open access)
    4. Semantic requirement matching
    5. ML-based relevance scoring
    6. Auto-generate submissions for high-quality candidates
    """
    
    def __init__(self, hunt_config: HuntConfig):
        """
        Initialize hunt orchestrator
        
        Args:
            hunt_config: Hunt configuration
        """
        self.config = hunt_config
        
        # Initialize components
        self.search_engine = AdvancedSearchEngine(hunt_config.study_folder)
        self.duplicate_detector = DuplicateDetector(hunt_config.study_folder.parent)

        self.semantic_matcher = SemanticMatcher()
        self.relevance_scorer = RelevanceScorer()
        self.submission_generator = SubmissionGenerator()
        
        # Load study data
        self._load_study_data()
        
        # Hunt statistics
        self.stats = {
            'sources_searched': 0,
            'total_found': 0,
            'filtered_known': 0,
            'filtered_paywall': 0,
            'filtered_low_score': 0,
            'candidates_generated': 0,
            'ready_submit': 0,
            'hold': 0
        }
    
    def _load_study_data(self):
        """Load study requirements and known art"""
        possible_config_paths = [
            self.config.study_folder / "STUDY_META.json",
            self.config.study_folder / "study_config.json",
            Path("config") / f"{self.config.study_id}_config.json"
        ]
        
        requirements = []
        for config_path in possible_config_paths:
            if config_path.exists():
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        study_data = json.load(f)
                        raw_reqs = study_data.get('requirements', [])
                        if raw_reqs:
                            requirements = [
                                {
                                    **req,
                                    "text": req.get("text") or req.get("name", "") or req.get("description", ""),
                                    "must_show_elements": req.get("must_show_elements", []),
                                    "keywords": req.get("keywords", [])
                                }
                                for req in raw_reqs
                            ]
                            print(f" [+] Loaded {len(requirements)} study requirements from {config_path.name}")
                            break
                except Exception as e:
                    print(f"  [!] Error loading study config from {config_path}: {e}")
                    
        self.study_requirements = requirements
        if requirements:
            self.semantic_matcher.load_requirements(self.config.study_id, requirements)
        else:
            print(f"  [!] Warning: No requirement definition found for study {self.config.study_id}")


        
        # Load known art for duplicate detection
        known_art_path = self.config.study_folder / "known_art" / "known_citations.csv"
        if known_art_path.exists():
            import csv
            known_art = []
            with open(known_art_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    known_art.append(row)
            self.duplicate_detector.load_known_art(self.config.study_id, known_art)
    
    def execute_hunt(self) -> Dict:
        """
        Execute full automated hunt across all sources
        
        Returns:
            Hunt results with statistics and candidate files
        """
        print(f"\n{'='*70}")
        print(f"AUTOMATED HUNT: Study {self.config.study_id}")
        print(f"Critical Date: {self.config.critical_date}")
        print(f"Keywords: {', '.join(self.config.keywords[:5])}")
        print(f"{'='*70}\n")
        
        # Step A: Keyword expansion lattice
        if KeywordExpander:
            try:
                expander = KeywordExpander()
                expanded = expander.expand_keywords(self.config.keywords)
                if expanded:
                    orig_count = len(self.config.keywords)
                    self.config.keywords = list(dict.fromkeys(self.config.keywords + expanded))

                    print(f" [+] Expanded keyword lattice: {orig_count} -> {len(self.config.keywords)} terms active\n")
            except Exception as e:
                print(f"  [!] Keyword expansion skipped: {e}\n")

        # Build query config for all enabled sources
        query_config = self._build_query_config()
        
        # Phase 1: Search all unconventional sources
        print("Phase 1: Searching unconventional sources...")
        search_results = self.search_engine.search_all_sources(
            query_config,
            max_results_per_source=self.config.max_results_per_source
        )
        
        # Phase 1b: Product Evidence Lane (L7)
        product_kw = self.config.keywords[:5] + (self.config.part_numbers or [])
        tech_terms = self.config.keywords[5:10] if len(self.config.keywords) > 5 else self.config.keywords[:3]
        l7_results = self.search_engine.search_product_lane(
            product_keywords=product_kw,
            technical_terms=tech_terms,
            before_date=self.config.critical_date,
            max_per_source=self.config.max_results_per_source
        )
        if l7_results:
            search_results.extend(l7_results)
            search_results = self.search_engine._filter_and_deduplicate(search_results)
        
        self.stats['total_found'] = len(search_results)
        self.stats['filtered_known'] = self.search_engine.stats['filtered_known']
        self.stats['filtered_paywall'] = self.search_engine.stats['filtered_paywall']
        
        print(f" [+] Found {len(search_results)} unique results across all lanes")
        print(f"  Filtered {self.stats['filtered_known']} known citations")
        print(f"  Filtered {self.stats['filtered_paywall']} paywalled documents\n")

        
        if not search_results:
            print("No new candidates found. Hunt complete.\n")
            return self._generate_hunt_report([])
        
        # Phase 2: Process candidates through AI pipeline
        print("Phase 2: Processing candidates through AI pipeline...")
        candidates = self._process_candidates(search_results)
        
        print(f" [+] Generated {len(candidates)} candidate submissions")
        print(f"  READY_SUBMIT: {self.stats['ready_submit']}")
        print(f"  HOLD: {self.stats['hold']}")
        print(f"  Filtered (low score): {self.stats['filtered_low_score']}\n")
        
        # Phase 3: Write submissions to files
        print("Phase 3: Writing submissions to files...")
        output_files = self._write_submissions(candidates)
        
        print(f" [+] Wrote {len(output_files)} submission files\n")
        
        # Generate hunt report
        report = self._generate_hunt_report(candidates)
        
        print(f"{'='*70}")
        print(f"HUNT COMPLETE")
        print(f"{'='*70}\n")
        
        return report
    
    def _build_query_config(self) -> Dict:
        """Build query configuration for all enabled sources"""
        date_range = ('1990-01-01', self.config.critical_date)
        
        query_config = {}
        
        # Wayback Machine
        if self.config.enable_wayback and self.config.target_domains:
            query_config['wayback'] = {
                'domain': self.config.target_domains[0],  # Primary domain
                'keywords': self.config.keywords,
                'date_range': date_range,
                'max_results': self.config.max_results_per_source
            }
        
        # FCC OET
        if self.config.enable_fcc and self.config.part_numbers:
            query_config['fcc'] = {
                'product_name': self.config.part_numbers[0],
                'manufacturer': self.config.manufacturers[0] if self.config.manufacturers else '',
                'date_range': date_range,
                'max_results': self.config.max_results_per_source
            }
        
        # USPTO PTAB
        if self.config.enable_ptab and self.config.patent_number:
            query_config['ptab'] = {
                'patent_number': self.config.patent_number,
                'max_results': self.config.max_results_per_source * 2  # More for PTAB
            }
        
        # USENET (Google Groups)
        if self.config.enable_usenet:
            query_config['usenet'] = {
                'keywords': self.config.keywords + self.config.part_numbers,
                'newsgroups': [
                    'comp.arch.embedded',
                    'sci.electronics.design',
                    'comp.sys.embedded',
                    'sci.electronics.components'
                ],
                'date_range': date_range,
                'max_results': self.config.max_results_per_source
            }
        
        # University archives
        if self.config.enable_university:
            query_config['university'] = {
                'keywords': self.config.keywords + self.config.part_numbers,
                'universities': [
                    'mit.edu', 'stanford.edu', 'berkeley.edu', 'cmu.edu',
                    'tudelft.nl', 'ethz.ch', 'kaist.ac.kr'
                ],
                'date_range': date_range,
                'max_results': self.config.max_results_per_source
            }
        
        # Distributor archives
        if self.config.enable_distributor and self.config.part_numbers:
            query_config['distributor'] = {
                'part_number': self.config.part_numbers[0],
                'distributors': ['digikey', 'mouser', 'arrow', 'avnet', 'newark'],
                'date_range': date_range,
                'max_results': self.config.max_results_per_source
            }
        
        # Internet Archive texts
        if self.config.enable_archive_texts:
            query_config['archive_texts'] = {
                'keywords': self.config.keywords,
                'date_range': date_range,
                'max_results': self.config.max_results_per_source
            }
        
        # GitHub/GitLab
        if self.config.enable_github:
            query_config['github'] = {
                'keywords': self.config.keywords + self.config.part_numbers,
                'date_range': date_range,
                'max_results': self.config.max_results_per_source
            }
        
        # Technical forums
        if self.config.enable_forums:
            query_config['forums'] = {
                'keywords': self.config.keywords + self.config.part_numbers,
                'forums': [
                    'stackoverflow',
                    'electronics.stackexchange',
                    'reddit.com/r/embedded',
                    'reddit.com/r/electronics'
                ],
                'date_range': date_range,
                'max_results': self.config.max_results_per_source
            }
        
        self.stats['sources_searched'] = len(query_config)
        return query_config
    
    def _process_candidates(self, search_results: List[SearchResult]) -> List[Dict]:
        """Process search results through AI pipeline"""
        candidates = []
        
        for result in search_results:
            # Convert SearchResult to metadata dict
            metadata = {
                'title': result.title,
                'url': result.url,
                'date': result.date,
                'source': result.source,
                'open_access': result.open_access,
                **result.metadata
            }
            
            # TODO: Fetch full text for semantic matching
            # For now, use snippet as text
            document_text = result.snippet
            
            # Semantic matching
            matches = self.semantic_matcher.match_document(
                self.config.study_id,
                document_text,
                metadata,
                min_confidence=self.config.min_confidence
            )
            
            if not matches:
                self.stats['filtered_low_score'] += 1
                continue
            
            # ML scoring
            study_config = {
                'study_id': self.config.study_id,
                'critical_date': self.config.critical_date,
                'type': 'invalidity',
                'requirements': getattr(self, 'study_requirements', [])
            }

            
            features = self.relevance_scorer.extract_features(
                metadata,
                matches,
                study_config
            )
            
            scoring_result = self.relevance_scorer.score_candidate(features)
            
            # Fallback match metadata tagging and safety gate
            has_fallback = any(getattr(m, 'requirement_id', '') == "REQ-FALLBACK" for m in matches)
            if has_fallback:
                metadata["match_mode"] = "fallback"
                metadata["requires_manual_review"] = True
                scoring_result.recommendation = "HOLD"

            # Generate submission
            submission = self.submission_generator.generate_submission(
                metadata,
                matches,
                scoring_result,
                study_config,
                document_text
            )
            
            candidates.append({
                'search_result': result,
                'metadata': metadata,
                'matches': matches,
                'scoring': scoring_result,
                'submission': submission
            })
            
            self.stats['candidates_generated'] += 1
            
            # Increment statistics ONCE based on final submission tier
            if submission.tier == 'READY_SUBMIT':
                self.stats['ready_submit'] += 1
            elif submission.tier == 'HOLD':
                self.stats['hold'] += 1

        
        return candidates
    
    def _write_submissions(self, candidates: List[Dict]) -> List[Path]:
        """Write submission files to candidates folder"""
        output_dir = self.config.study_folder / "candidates"
        output_dir.mkdir(exist_ok=True)
        
        output_files = []
        
        for candidate in candidates:
            submission = candidate['submission']
            
            # Format submission
            formatted = self.submission_generator.format_for_portal(submission)
            
            # Write to file
            output_path = output_dir / submission.filename
            output_path.write_text(formatted, encoding='utf-8')
            
            output_files.append(output_path)
        
        return output_files
    
    def _generate_hunt_report(self, candidates: List[Dict]) -> Dict:
        """Generate hunt report"""
        return {
            'study_id': self.config.study_id,
            'timestamp': datetime.now().isoformat(),
            'statistics': self.stats,
            'candidates': [
                {
                    'title': c['metadata']['title'],
                    'source': c['search_result'].source,
                    'url': c['metadata']['url'],
                    'date': c['metadata']['date'],
                    'tier': c['submission'].tier,
                    'rank': c['scoring'].predicted_rank,
                    'confidence': c['scoring'].rank_confidence,
                    'filename': c['submission'].filename
                }
                for c in candidates
            ],
            'summary': {
                'sources_searched': self.stats['sources_searched'],
                'total_found': self.stats['total_found'],
                'after_filtering': self.stats['candidates_generated'],
                'ready_to_submit': self.stats['ready_submit'],
                'success_rate': (
                    self.stats['ready_submit'] / self.stats['total_found']
                    if self.stats['total_found'] > 0 else 0.0
                )
            }
        }


# Example usage
if __name__ == "__main__":
    # Configure hunt for study 25657 (Philips PN511/PN531)
    hunt_config = HuntConfig(
        study_id="25657",
        study_folder=Path("25657_Integrated_Circuit_Chips"),
        critical_date="2005-01-10",
        keywords=[
            "PN511", "PN531", "PN512", "NFC", "near field communication",
            "contactless", "RFID", "13.56 MHz", "ISO 14443", "Philips Semiconductors"
        ],
        part_numbers=["PN511", "PN531", "PN512"],
        manufacturers=["Philips", "NXP"],
        target_domains=[
            "semiconductors.philips.com",
            "nxp.com",
            "philips.com"
        ],
        patent_number="7373531",
        enable_wayback=True,
        enable_fcc=True,
        enable_ptab=True,
        enable_usenet=True,
        enable_university=True,
        enable_distributor=True,
        enable_archive_texts=True,
        enable_github=True,
        enable_forums=True,
        max_results_per_source=20,
        min_confidence=0.6
    )
    
    # Execute hunt
    orchestrator = HuntOrchestrator(hunt_config)
    report = orchestrator.execute_hunt()
    
    # Print summary
    print("\nHunt Summary:")
    print(f"  Sources searched: {report['summary']['sources_searched']}")
    print(f"  Total found: {report['summary']['total_found']}")
    print(f"  After filtering: {report['summary']['after_filtering']}")
    print(f"  Ready to submit: {report['summary']['ready_to_submit']}")
    print(f"  Success rate: {report['summary']['success_rate']:.1%}")
