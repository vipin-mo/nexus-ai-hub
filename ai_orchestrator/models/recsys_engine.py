import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

class EnterpriseRecommendationEngine:
    def __init__(self):
        # Explicit mock inventory matching tool tokens to action parameters
        self.tool_catalog = [
            "TOOL_01: RELATIONAL_POSTGRES_EXPORT",
            "TOOL_02: AUTOMATED_JIRA_TICKET_GEN",
            "TOOL_03: SECURITY_AUDIT_LOG_FREEZE",
            "TOOL_04: REVENUE_REFUND_DISPATCH_GATE"
        ]

    def generate_personalized_recommendations(self, user_id: int, historical_matrix: np.ndarray) -> list:
        """
        Executes item-based collaborative filtering via Cosine Similarity matrix transformations.
        Calculates similarity vectors across enterprise tool sets to identify matching user workflows.
        """
        if user_id >= historical_matrix.shape[0]:
            print(f"⚠️ [RecSys Matrix Error] Requested User Index {user_id} falls outside matrix boundaries.")
            return []

        # Step 1: Compute the tool-to-tool affinity similarity matrix
        tool_similarity = cosine_similarity(historical_matrix.T)

        # Step 2: Grab interaction maps for the current user matching user_id index
        user_ratings = historical_matrix[user_id]

        # Step 3: Compute localized dot product scoring matrix
        scores = tool_similarity.dot(user_ratings)

        # Step 4: Mask tools the current employee has already frequently executed to keep recommendations unique
        for index, rating in enumerate(user_ratings):
            if index < len(scores) and rating > 0.7:  # Threshold marking tool saturation safety boundary
                scores[index] = -1.0

        # Step 5: Extract the highest affinity indices
        ranked_indices = np.argsort(scores)[::-1]

        recommended_tools = []
        for idx in ranked_indices:
            if idx < len(self.tool_catalog) and scores[idx] > 0:  # Enforce positive similarity vectors
                recommended_tools.append(self.tool_catalog[idx])

        return recommended_tools

if __name__ == "__main__":
    print("Initializing collaborative filtering matrix arrays...")

    # Rows: 4 Employees, Columns: 4 Enterprise Tools
    mock_interaction_matrix = np.array([
        [1.0, 0.2, 0.0, 0.0],  # Employee 0: Database Administrator profile
        [0.0, 0.9, 0.8, 0.1],  # Employee 1: Security SecOps team profile
        [0.1, 0.0, 0.0, 1.0],  # Employee 2: Financial Account manager profile
        [0.8, 0.3, 0.0, 0.0]   # Employee 3: Target testing user profile
    ])

    engine = EnterpriseRecommendationEngine()
    target_user_index = 3
    results = engine.generate_personalized_recommendations(target_user_index, mock_interaction_matrix)

    print(f"\n[RecSys Computation Complete] Top Affinity Actions Calculated for User {target_user_index}:")
    for rank, tool in enumerate(results, 1):
        print(f"   {rank}. {tool}")
