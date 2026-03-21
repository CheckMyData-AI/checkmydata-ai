"""Import all ORM models so SQLAlchemy's mapper can resolve every relationship."""

from app.models.agent_learning import AgentLearning  # noqa: F401
from app.models.backup_record import BackupRecord  # noqa: F401
from app.models.chat_session import ChatMessage, ChatSession  # noqa: F401
from app.models.code_db_sync import CodeDbSync  # noqa: F401
from app.models.commit_index import CommitIndex  # noqa: F401
from app.models.connection import Connection  # noqa: F401
from app.models.custom_rule import CustomRule  # noqa: F401
from app.models.db_index import DbIndex  # noqa: F401
from app.models.indexing_checkpoint import IndexingCheckpoint  # noqa: F401
from app.models.knowledge_doc import KnowledgeDoc  # noqa: F401
from app.models.notification import Notification  # noqa: F401
from app.models.pipeline_run import PipelineRun  # noqa: F401
from app.models.project import Project  # noqa: F401
from app.models.project_cache import ProjectCache  # noqa: F401
from app.models.project_invite import ProjectInvite  # noqa: F401
from app.models.project_member import ProjectMember  # noqa: F401
from app.models.rag_feedback import RAGFeedback  # noqa: F401
from app.models.repository import ProjectRepository  # noqa: F401
from app.models.saved_note import SavedNote  # noqa: F401
from app.models.scheduled_query import ScheduledQuery, ScheduleRun  # noqa: F401
from app.models.ssh_key import SshKey  # noqa: F401
from app.models.token_usage import TokenUsage  # noqa: F401
from app.models.user import User  # noqa: F401
