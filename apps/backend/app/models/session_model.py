from typing import Dict, List, Optional, Any
from datetime import datetime


class SessionStore:
    def __init__(self):
        self._sessions: List[Dict[str, Any]] = []

    def save_session(self, session_data: Dict[str, Any]) -> None:
        self._sessions.insert(0, session_data)
        if len(self._sessions) > 50:
            self._sessions.pop()

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        for sess in self._sessions:
            if sess.get("id") == session_id:
                return sess
        return None

    
    def delete_session(self, session_id: str) -> bool:
        initial_len = len(self._sessions)
        self._sessions = [s for s in self._sessions if s.get("id") != session_id]
        return len(self._sessions) < initial_len

    def get_all_sessions(self) -> List[Dict[str, Any]]:
        return list(self._sessions)

    def get_history_comparison(self, current_audit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if len(self._sessions) < 2:
            return None
        previous = self._sessions[1].get("auditResult", {})
        curr_score = current_audit.get("executive_summary", {}).get("health_score", {}).get("score", 0)
        prev_score = previous.get("executive_summary", {}).get("health_score", {}).get("score", 0)

        curr_recs = {r["code"] for r in current_audit.get("recommendations", [])}
        prev_recs = {r["code"] for r in previous.get("recommendations", [])}

        new_issues = list(curr_recs - prev_recs)
        resolved_issues = list(prev_recs - curr_recs)

        return {
            "previousDate": previous.get("executive_summary", {}).get("audit_date", ""),
            "currentDate": current_audit.get("executive_summary", {}).get("audit_date", ""),
            "scoreChange": round(curr_score - prev_score, 1),
            "previousScore": prev_score,
            "currentScore": curr_score,
            "newIssuesCount": len(new_issues),
            "resolvedIssuesCount": len(resolved_issues),
            "newIssues": new_issues,
            "resolvedIssues": resolved_issues,
            "pagesCountDelta": len(current_audit.get("pages", [])) - len(previous.get("pages", [])),
        }


session_store = SessionStore()
