"""Every model, imported here so that `import app.models` registers all of
them on `Base.metadata`.

That completeness is load-bearing, not tidiness: tests build their schema
with `create_all()`, and a model missing from this list simply has no table -
which surfaces as a confusing NoReferencedTableError from whichever *other*
model happens to have a foreign key to it. Four were missing when that was
first noticed (attention_item, channel_ai_history, channel_connection,
meeting_brief), and each one only failed in the tests unlucky enough not to
import it by another route.
"""

from app.models.action import Action
from app.models.action_policy import ActionPolicy
from app.models.attention_item import AttentionItem
from app.models.agent_run import AgentRun
from app.models.base import Base
from app.models.brief import Brief
from app.models.channel_ai_history import ChannelAIHistoryEntry
from app.models.channel_connection import ChannelConnection, ChannelConnectionResource
from app.models.channel_required_connection import ChannelRequiredConnection
from app.models.commitment import Commitment
from app.models.connection import Connection
from app.models.shared_connection import ChannelConnectionExclusion, SharedConnection, SharedConnectionResource
from app.models.hierarchy import Group, WorkspaceClass
from app.models.email_summary import EmailSummary
from app.models.finding import AgentFinding
from app.models.goal import Goal, GoalCommitment
from app.models.investigation import Investigation
from app.models.invite import WorkspaceInvite
from app.models.meeting_brief import MeetingBrief
from app.models.otp_code import OtpCode
from app.models.signal import Signal
from app.models.situation import Situation
from app.models.team import Team, TeamMembership
from app.models.user import User
from app.models.workspace import Membership, Workspace

__all__ = [
    "Base",
    "User",
    "OtpCode",
    "Workspace",
    "Membership",
    "Team",
    "TeamMembership",
    "WorkspaceInvite",
    "WorkspaceClass",
    "Group",
    "Connection",
    "SharedConnection",
    "ChannelConnectionExclusion",
    "SharedConnectionResource",
    "ChannelRequiredConnection",
    "Signal",
    "AgentRun",
    "AgentFinding",
    "Brief",
    "EmailSummary",
    "Investigation",
    "Situation",
    "Commitment",
    "Goal",
    "GoalCommitment",
    "Action",
    "ActionPolicy",
    "AttentionItem",
    "ChannelAIHistoryEntry",
    "ChannelConnection",
    "ChannelConnectionResource",
    "MeetingBrief",
]
