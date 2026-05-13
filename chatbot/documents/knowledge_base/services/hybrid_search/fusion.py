"""
Result Fusion and Ranking
Handles the fusion and ranking of search results from multiple strategies
"""

import logging
from typing import List, Dict
from .strategies import SearchStrategy
from .models import SearchResult

logger = logging.getLogger(__name__)

class ResultFusion:
    """Handles fusion and ranking of search results"""
    
    @classmethod
    def fuse_and_rank_results(cls, all_results: Dict[SearchStrategy, List[SearchResult]]) -> List[SearchResult]:
        """Fusioniert und rankt Ergebnisse aus verschiedenen Strategien"""
        # Sammle alle einzigartigen Dokumente
        doc_scores = {}
        
        for strategy, results in all_results.items():
            for result in results:
                doc_id = result.doc_id
                
                if doc_id not in doc_scores:
                    doc_scores[doc_id] = {
                        'result': result,
                        'total_score': 0,
                        'strategies': []
                    }
                
                # Addiere Score
                doc_scores[doc_id]['total_score'] += result.relevance_score
                doc_scores[doc_id]['strategies'].append(strategy)
                
                # Update mit besserem Snippet wenn vorhanden
                if result.snippet and len(result.snippet) > len(doc_scores[doc_id]['result'].snippet):
                    doc_scores[doc_id]['result'].snippet = result.snippet
                
                # Merge matched chunks
                if result.matched_chunks:
                    doc_scores[doc_id]['result'].matched_chunks.extend(result.matched_chunks)
        
        # Bonus für Dokumente die in mehreren Strategien gefunden wurden
        for doc_data in doc_scores.values():
            strategy_bonus = len(doc_data['strategies']) * 0.5
            doc_data['total_score'] *= (1 + strategy_bonus)
            doc_data['result'].relevance_score = doc_data['total_score']
        
        # Sortiere nach Score
        ranked = sorted(doc_scores.values(), key=lambda x: x['total_score'], reverse=True)
        
        return [item['result'] for item in ranked]