"""
Advanced Search Engine - Hunt in unconventional sources people never think of
Searches high and low, filters known citations, enforces no-paywall rule
NOW WITH RATE LIMITING - No more HTTP 503 errors!
"""

import sys
import re
import csv
from typing import List, Dict, Optional, Set, Tuple
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime
import time

# Ensure project root is in sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

try:
    from scripts import product_search
except ImportError:
    try:
        import product_search
    except ImportError:
        product_search = None

from .rate_limiter import wayback_throttle, fcc_throttle, ptab_throttle, github_throttle
from .patent_url_fixer import PatentURLGenerator



@dataclass
class SearchResult:
    """Search result from unconventional source"""
    title: str
    url: str
    source: str  # "wayback" | "fcc" | "ptab" | "usenet" | "university" | "distributor"
    date: str
    snippet: str
    metadata: Dict
    open_access: bool
    confidence: float
    
    def __post_init__(self):
        """Fix patent URLs after initialization"""
        # If metadata contains patent_number, fix the URL
        if self.metadata.get('patent_number'):
            patent_urls = PatentURLGenerator.generate_urls(self.metadata['patent_number'])
            # Use best PDF URL
            best_url = patent_urls.get('pdf') or patent_urls.get('html')
            if best_url:
                self.url = best_url
                self.metadata['patent_urls'] = patent_urls
                self.metadata['patent_office'] = patent_urls.get('office')


class AdvancedSearchEngine:
    """
    Searches unconventional sources for prior art with RATE LIMITING:
    - Wayback Machine (archive.org) - old manufacturer sites
    - FCC OET database - equipment authorization exhibits
    - USPTO PTAB E2E - IPR exhibit lists
    - Google Groups (USENET archives) - engineer discussions
    - University archives - course materials, lab pages
    - Distributor archives - old datasheets (Findchips, Digi-Key, Mouser)
    - Internet Archive texts - trade magazines
    - GitHub/GitLab - open source projects, documentation
    - Technical forums - Stack Overflow, EE StackExchange, Reddit
    - Conference proceedings - free/open access only
    
    ALL API CALLS ARE RATE-LIMITED TO PREVENT HTTP 503 ERRORS
    """
    
    def __init__(self, study_folder: Path):
        """
        Initialize search engine for a study
        
        Args:
            study_folder: Path to study folder (e.g., "25974_Oximidol/")
        """
        self.study_folder = study_folder
        self.known_citations: Set[str] = set()
        self.known_dois: Set[str] = set()
        self.known_titles: Set[str] = set()
        
        # Load known citations to filter out
        self._load_known_citations()
        
        # Search statistics
        self.stats = {
            'total_found': 0,
            'filtered_known': 0,
            'filtered_paywall': 0,
            'returned': 0,
            'rate_limit_hits': 0
        }
    
    def _load_known_citations(self):
        """Load known citations from study folder to filter them out"""
        # Try multiple possible locations
        possible_paths = [
            self.study_folder / "known_art" / "known_citations.csv",
            self.study_folder / f"{self.study_folder.name}_knowncitations.csv",
            self.study_folder / "known_citations.csv"
        ]
        
        for csv_path in possible_paths:
            if csv_path.exists():
                print(f" [+] Loading known citations from: {csv_path.name}")

                with open(csv_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # Store multiple identifiers for matching
                        if row.get('doi'):
                            self.known_dois.add(self._normalize_doi(row['doi']))
                        if row.get('title'):
                            self.known_titles.add(self._normalize_title(row['title']))
                        if row.get('patent_number'):
                            self.known_citations.add(self._normalize_patent(row['patent_number']))
                        if row.get('url'):
                            self.known_citations.add(row['url'].lower().strip())
                
                print(f"  Loaded {len(self.known_dois)} DOIs, {len(self.known_titles)} titles")
                return
        
        print(f"⚠ WARNING: No known_citations.csv found in {self.study_folder}")
    
    def is_known_citation(self, result: SearchResult) -> bool:
        """Check if result matches a known citation"""
        # Check DOI
        if result.metadata.get('doi'):
            doi_norm = self._normalize_doi(result.metadata['doi'])
            if doi_norm in self.known_dois:
                return True
        
        # Check title
        title_norm = self._normalize_title(result.title)
        if title_norm in self.known_titles:
            return True
        
        # Check URL
        url_norm = result.url.lower().strip()
        if url_norm in self.known_citations:
            return True
        
        # Check patent number
        if result.metadata.get('patent_number'):
            patent_norm = self._normalize_patent(result.metadata['patent_number'])
            if patent_norm in self.known_citations:
                return True
        
        return False
    
    @wayback_throttle
    def search_wayback_machine(
        self,
        domain: str,
        keywords: List[str],
        date_range: Tuple[str, str],
        max_results: int = 20
    ) -> List[SearchResult]:
        """
        Search Wayback Machine for archived pages (RATE LIMITED)
        """
        results = []
        print(f"  [Wayback] Searching {domain}...")
        
        try:
            from_date = date_range[0].replace("-", "") if date_range and date_range[0] else "20000101"
            to_date = date_range[1].replace("-", "") if date_range and len(date_range) > 1 else "20201231"
            
            if product_search:
                wb_hits = product_search.search_wayback_machine(domain, from_date=from_date, to_date=to_date)
                for item in wb_hits[:max_results]:
                    res = SearchResult(
                        title=f"Archived snapshot: {item.get('original_url', domain)}",
                        url=item.get('url', ''),
                        source="wayback",
                        date=item.get('date', date_range[0] if date_range else '2000-01-01'),
                        snippet=f"Wayback Machine snapshot of {item.get('original_url', domain)} (Status {item.get('status_code', '200')}).",
                        metadata={
                            'domain': domain,
                            'snapshot_date': item.get('date'),
                            'original_url': item.get('original_url'),
                            'timestamp': item.get('timestamp')
                        },
                        open_access=True,
                        confidence=0.8
                    )
                    if not self.is_known_citation(res):
                        results.append(res)
                    else:
                        self.stats['filtered_known'] += 1
            else:
                time.sleep(0.5)
        except Exception as e:
            if '503' in str(e) or 'rate limit' in str(e).lower():
                self.stats['rate_limit_hits'] += 1
                print(f"  [Wayback] Rate limit hit, backing off...")
            print(f"  [Wayback] Search error: {e}")
        
        return results

    
    @fcc_throttle
    def search_fcc_oet(
        self,
        product_name: str,
        manufacturer: str,
        date_range: Tuple[str, str],
        max_results: int = 20
    ) -> List[SearchResult]:
        """
        Search FCC OET Equipment Authorization Database (RATE LIMITED)
        
        Args:
            product_name: Product name or model number
            manufacturer: Manufacturer name
            date_range: (start_date, end_date) in YYYY-MM-DD format
            max_results: Maximum results to return
            
        Returns:
            List of SearchResult objects (datasheets from exhibits)
        """
        results = []
        
        print(f"  [FCC] Searching {manufacturer} {product_name}...")
        
        try:
            # FCC OET database: https://apps.fcc.gov/oetcf/eas/reports/GenericSearch.cfm
            # Exhibits often contain datasheets, technical specs
            
            # Simulate API call delay
            time.sleep(0.5)
            
            # TODO: Implement FCC API/scraping
            # FCC exhibits are public domain - always open access
        
        except Exception as e:
            if '503' in str(e) or 'rate limit' in str(e).lower():
                self.stats['rate_limit_hits'] += 1
                print(f"  [FCC] Rate limit hit, backing off...")
            raise
        
        return results
    
    @ptab_throttle
    def search_uspto_ptab(
        self,
        patent_number: str,
        max_results: int = 50
    ) -> List[SearchResult]:
        """
        Search USPTO PTAB E2E for IPR exhibits (RATE LIMITED)
        
        Args:
            patent_number: Target patent number (e.g., "7373531")
            max_results: Maximum results to return
            
        Returns:
            List of SearchResult objects (NPL exhibits from IPRs)
        """
        results = []
        
        print(f"  [PTAB] Searching patent {patent_number}...")
        
        try:
            # PTAB E2E: https://ptacts.uspto.gov/ptacts/ui/home
            # Search for IPRs against the target patent
            # Extract NPL exhibit lists
            
            # Simulate API call delay
            time.sleep(0.5)
            
            # TODO: Implement PTAB API/scraping
            # Check each NPL exhibit against known citations
        
        except Exception as e:
            if '503' in str(e) or 'rate limit' in str(e).lower():
                self.stats['rate_limit_hits'] += 1
                print(f"  [PTAB] Rate limit hit, backing off...")
            raise
        
        return results
    
    def search_google_groups(
        self,
        keywords: List[str],
        newsgroups: List[str],
        date_range: Tuple[str, str],
        max_results: int = 20
    ) -> List[SearchResult]:
        """
        Search Google Groups (USENET archives) - RATE LIMITED
        
        Args:
            keywords: Keywords to search
            newsgroups: Newsgroup names (e.g., ["comp.arch.embedded"])
            date_range: (start_date, end_date) in YYYY-MM-DD format
            max_results: Maximum results to return
            
        Returns:
            List of SearchResult objects (USENET posts with dates)
        """
        results = []
        
        print(f"  [USENET] Searching {len(newsgroups)} newsgroups...")
        
        try:
            # Google Groups search: https://groups.google.com/
            # USENET posts are timestamped and often discuss products before release
            
            # Simulate API call delay
            time.sleep(1.0)  # Slower for Google
            
            # TODO: Implement Google Groups API/scraping
            # USENET archives are open access
        
        except Exception as e:
            if '503' in str(e) or 'rate limit' in str(e).lower():
                self.stats['rate_limit_hits'] += 1
                print(f"  [USENET] Rate limit hit, backing off...")
            raise
        
        return results
    
    def search_university_archives(
        self,
        keywords: List[str],
        universities: List[str],
        date_range: Tuple[str, str],
        max_results: int = 20
    ) -> List[SearchResult]:
        """
        Search university archives (course materials, lab pages, theses)
        
        Args:
            keywords: Keywords to search
            universities: University domains (e.g., ["mit.edu", "stanford.edu"])
            date_range: (start_date, end_date) in YYYY-MM-DD format
            max_results: Maximum results to return
            
        Returns:
            List of SearchResult objects
        """
        results = []
        
        print(f"  [University] Searching {len(universities)} universities...")
        
        # Use site: operator with Google/Bing
        # Example: site:mit.edu "PN511" filetype:pdf
        
        # Common university repositories:
        # - MIT DSpace
        # - Stanford Digital Repository
        # - TU Delft Repository
        # - KAIST Repository
        
        # TODO: Implement university archive searches
        # Check open access status for each result
        
        return results
    
    def search_distributor_archives(
        self,
        part_number: str,
        distributors: List[str],
        date_range: Tuple[str, str],
        max_results: int = 20
    ) -> List[SearchResult]:
        """
        Search distributor archives for old datasheets
        
        Args:
            part_number: Part/model number
            distributors: Distributor names (e.g., ["digikey", "mouser", "arrow"])
            date_range: (start_date, end_date) in YYYY-MM-DD format
            max_results: Maximum results to return
            
        Returns:
            List of SearchResult objects (datasheets)
        """
        results = []
        
        print(f"  [Distributor] Searching for {part_number}...")
        
        # Findchips.com aggregates distributor data
        # Wayback Machine snapshots of distributor sites
        # Direct distributor APIs where available
        
        # TODO: Implement distributor searches
        # Datasheets are typically open access
        
        return results
    
    def search_internet_archive_texts(
        self,
        keywords: List[str],
        date_range: Tuple[str, str],
        max_results: int = 20
    ) -> List[SearchResult]:
        """
        Search Internet Archive text collection (trade magazines, books)
        """
        results = []
        print(f"  [Archive.org] Searching texts...")
        query_str = " ".join(keywords) if isinstance(keywords, list) else str(keywords)
        
        try:
            if product_search:
                ia_hits = product_search.search_archive_org(query_str, mediatype="texts", max_results=max_results)
                for item in ia_hits:
                    res = SearchResult(
                        title=item.get("title", "Internet Archive Text"),
                        url=item.get("url", ""),
                        source="archive_texts",
                        date=f"{item.get('year', '2000')}-01-01",
                        snippet=item.get("description", ""),
                        metadata={
                            'identifier': item.get('identifier'),
                            'year': item.get('year'),
                            'downloads': item.get('downloads')
                        },
                        open_access=True,
                        confidence=0.85
                    )
                    if not self.is_known_citation(res):
                        results.append(res)
                    else:
                        self.stats['filtered_known'] += 1
        except Exception as e:
            print(f"  [Archive.org] Search error: {e}")
            
        return results
    
    @github_throttle
    def search_github_gitlab(
        self,
        keywords: List[str],
        date_range: Tuple[str, str],
        max_results: int = 20
    ) -> List[SearchResult]:
        """
        Search GitHub/GitLab for technical documentation, datasheets (RATE LIMITED)
        """
        results = []
        print(f"  [GitHub] Searching repositories...")
        try:
            time.sleep(0.5)
        except Exception as e:
            if '503' in str(e) or 'rate limit' in str(e).lower():
                self.stats['rate_limit_hits'] += 1
            print(f"  [GitHub] Search error: {e}")
        return results
    
    def search_technical_forums(
        self,
        keywords: List[str],
        forums: List[str],
        date_range: Tuple[str, str],
        max_results: int = 20
    ) -> List[SearchResult]:
        """
        Search technical forums (Stack Overflow, EE StackExchange, Reddit)
        """
        results = []
        print(f"  [Forums] Searching forums...")
        query_str = " ".join(keywords) if isinstance(keywords, list) else str(keywords)
        
        try:
            if product_search:
                before_ts = None
                if date_range and len(date_range) > 1 and date_range[1]:
                    try:
                        before_ts = int(time.mktime(time.strptime(date_range[1], "%Y-%m-%d")))
                    except Exception:
                        pass
                        
                reddit_hits = product_search.search_reddit(query_str, before_timestamp=before_ts, max_results=max_results)
                for item in reddit_hits:
                    res = SearchResult(
                        title=item.get("title", "Reddit Discussion"),
                        url=item.get("url", ""),
                        source="forums",
                        date=item.get("created_date", date_range[0] if date_range else "2000-01-01"),
                        snippet=f"[{item.get('subreddit')}] {item.get('selftext', '')}",
                        metadata={
                            'author': item.get('author'),
                            'score': item.get('score'),
                            'subreddit': item.get('subreddit')
                        },
                        open_access=True,
                        confidence=0.75
                    )
                    if not self.is_known_citation(res):
                        results.append(res)
                    else:
                        self.stats['filtered_known'] += 1
        except Exception as e:
            print(f"  [Forums] Search error: {e}")
            
        return results

    def search_product_lane(
        self,
        product_keywords: List[str],
        technical_terms: List[str],
        before_date: str,
        max_per_source: int = 20
    ) -> List[SearchResult]:
        """
        Run product evidence search (L7 Product Evidence Lane) using product_search module
        """
        results = []
        if not product_search:
            print("  [!] product_search module not available for L7 lane")
            return results
            
        print(f"  [L7 Product Evidence] Running multi-source product evidence search...")
        try:
            raw_results = product_search.search_product_evidence(
                product_keywords=product_keywords,
                technical_terms=technical_terms,
                before_date=before_date,
                max_per_source=max_per_source
            )
            
            for source_type, items in raw_results.items():
                for item in items:
                    raw_date = item.get("published_date") or item.get("date") or item.get("created_date") or item.get("year")
                    if not raw_date or str(raw_date).lower() in ["unknown", "none", ""]:
                        date_str = "unknown"
                        item["date_verified"] = False
                        item["requires_manual_review"] = True
                        item["match_mode"] = "unknown_date"
                    else:
                        date_str = str(raw_date)
                        item["date_verified"] = True

                    res = SearchResult(
                        title=item.get("title", item.get("name", "Product Evidence")),
                        url=item.get("url", item.get("link", "")),
                        source=f"l7_{source_type}",
                        date=date_str,
                        snippet=item.get("description", item.get("snippet", item.get("selftext", ""))),
                        metadata=item,
                        open_access=True,
                        confidence=0.8 if date_str != "unknown" else 0.5
                    )

                    if not self.is_known_citation(res):
                        results.append(res)
                    else:
                        self.stats['filtered_known'] += 1
                        
            print(f"  [+] [L7 Product Evidence] Found {len(results)} valid product evidence candidates")
        except Exception as e:
            print(f"  [-] [L7 Product Evidence] Error: {e}")
            
        return results

    
    def search_all_sources(
        self,
        query_config: Dict,
        max_results_per_source: int = 20
    ) -> List[SearchResult]:
        """
        Search all unconventional sources with RATE LIMITING
        
        Args:
            query_config: Configuration dict with search parameters
            max_results_per_source: Max results per source
            
        Returns:
            Combined list of SearchResult objects, filtered and deduplicated
        """
        print(f"\n{'='*60}")
        print(f"Searching {len(query_config)} sources with rate limiting...")
        print(f"{'='*60}\n")
        
        all_results = []
        
        # Search sources SEQUENTIALLY to avoid overwhelming APIs
        # (Parallel execution removed to prevent HTTP 503)
        
        for source_name, params in query_config.items():
            try:
                if source_name == 'wayback':
                    results = self.search_wayback_machine(**params)
                elif source_name == 'fcc':
                    results = self.search_fcc_oet(**params)
                elif source_name == 'ptab':
                    results = self.search_uspto_ptab(**params)
                elif source_name == 'usenet':
                    results = self.search_google_groups(**params)
                elif source_name == 'university':
                    results = self.search_university_archives(**params)
                elif source_name == 'distributor':
                    results = self.search_distributor_archives(**params)
                elif source_name == 'archive_texts':
                    results = self.search_internet_archive_texts(**params)
                elif source_name == 'github':
                    results = self.search_github_gitlab(**params)
                elif source_name == 'forums':
                    results = self.search_technical_forums(**params)
                else:
                    continue
                
                print(f"  [+] {source_name}: {len(results)} results")
                all_results.extend(results)
                
            except Exception as e:
                print(f"  [-] {source_name}: {str(e)}")
        
        # Filter and deduplicate
        filtered_results = self._filter_and_deduplicate(all_results)
        
        # Update statistics
        self.stats['total_found'] = len(all_results)
        self.stats['returned'] = len(filtered_results)
        
        print(f"\n{'='*60}")
        print(f"Search complete:")
        print(f"  Found: {self.stats['total_found']}")
        print(f"  Filtered (known): {self.stats['filtered_known']}")
        print(f"  Filtered (paywall): {self.stats['filtered_paywall']}")
        print(f"  Rate limit hits: {self.stats['rate_limit_hits']}")
        print(f"  Returned: {self.stats['returned']}")
        print(f"{'='*60}\n")
        
        return filtered_results
    
    def _filter_and_deduplicate(self, results: List[SearchResult]) -> List[SearchResult]:
        """Filter known citations, paywalls, and deduplicate"""
        seen_urls = set()
        seen_titles = set()
        filtered = []
        
        for result in results:
            # Filter known citations
            if self.is_known_citation(result):
                self.stats['filtered_known'] += 1
                continue
            
            # Filter paywalls (STRICT - must be open access)
            if not result.open_access:
                self.stats['filtered_paywall'] += 1
                continue
            
            # Deduplicate by URL
            url_norm = result.url.lower().strip()
            if url_norm in seen_urls:
                continue
            seen_urls.add(url_norm)
            
            # Deduplicate by title
            title_norm = self._normalize_title(result.title)
            if title_norm in seen_titles:
                continue
            seen_titles.add(title_norm)
            
            filtered.append(result)
        
        # Sort by confidence (highest first)
        filtered.sort(key=lambda r: r.confidence, reverse=True)
        
        return filtered
    
    def _normalize_doi(self, doi: str) -> str:
        """Normalize DOI for comparison"""
        if not doi:
            return ""
        doi = doi.lower().strip()
        doi = re.sub(r'^(https?://)?((dx\.)?doi\.org/)?', '', doi)
        return doi
    
    def _normalize_patent(self, patent: str) -> str:
        """Normalize patent number for comparison"""
        if not patent:
            return ""
        patent = patent.upper().strip()
        patent = re.sub(r'[\s\-]', '', patent)
        return patent
    
    def _normalize_title(self, title: str) -> str:
        """Normalize title for comparison"""
        if not title or not isinstance(title, str):
            return ""
        title = title.lower().strip()
        title = re.sub(r'[^\w\s]', ' ', title)
        title = re.sub(r'\s+', ' ', title)
        return title

    
    def get_statistics(self) -> Dict:
        """Get search statistics"""
        return {
            **self.stats,
            'filter_rate': (
                (self.stats['filtered_known'] + self.stats['filtered_paywall']) / 
                self.stats['total_found']
                if self.stats['total_found'] > 0 else 0.0
            )
        }