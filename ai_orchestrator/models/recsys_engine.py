import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

class EnterpriseRecommendationEngine:
    def __init__(self):
        self.tool_catalog = [
            "TOOL_01: RELATIONAL_POSTGRES_EXPORT",
            "TOOL_02: AUTOMATED_JIRA_TICKET_GEN",
            "TOOL_03: SECURITY_AUDIT_LOG_FREEZE",
            "TOOL_04: REVENUE_REFUND_DISPATCH_GATE"
        ]

    def generate_personalized_recommendations(self, user_id: int, historical_matrix: np.ndarray) -> list:
        if historical_matrix is None or historical_matrix.ndim != 2:
            print("⚠️ [RecSys Error] Invalid matrix dimensions passed to processing node.")
            return []

        if user_id >= historical_matrix.shape[0]:
            print(f"⚠️ [RecSys Matrix Error] Requested User Index {user_id} falls outside matrix boundaries.")
            return []

        catalog_len = len(self.tool_catalog)
        if historical_matrix.shape[1] != catalog_len:
            print(f"⚠️ [RecSys Dimension Mismatch] Matrix columns ({historical_matrix.shape[1]}) must match Catalog size ({catalog_len}).")
            return []

        # Compute cosine similarity and safely convert NaNs resulting from zero-vector columns
        tool_similarity = cosine_similarity(historical_matrix.T)
        tool_similarity = np.nan_to_num(tool_similarity)

        user_ratings = historical_matrix[user_id]
        scores = tool_similarity.dot(user_ratings)

        # Mask saturated tools
        for index, rating in enumerate(user_ratings):
            if index < len(scores) and rating > 0.7:
                scores[index] = -1.0

        ranked_indices = np.argsort(scores)[::-1]

        recommended_tools = []
        for idx in ranked_indices:
            if idx < catalog_len and scores[idx] > 0:
                recommended_tools.append(self.tool_catalog[idx])

        return recommended_tools

if __name__ == "__main__":
    print("Initializing collaborative filtering matrix arrays...")
    mock_interaction_matrix = np.array([
        [1.0, 0.2, 0.0, 0.0],
        [0.0, 0.9, 0.8, 0.1],
        [0.1, 0.0, 0.0, 1.0],
        [0.8, 0.3, 0.0, 0.0]
    ])

    engine = EnterpriseRecommendationEngine()
    target_user_index = 3
    results = engine.generate_personalized_recommendations(target_user_index, mock_interaction_matrix)

    print(f"\n[RecSys Computation Complete] Top Affinity Actions Calculated for User {target_user_index}:")
    for rank, tool in enumerate(results, 1):
        print(f"   {rank}. {tool}")
