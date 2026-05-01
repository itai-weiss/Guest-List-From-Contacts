"""Guest list from contacts package."""

__version__ = "0.1.0"

from .matching import match_guest_rows
from .models import GuestRow, MatchCandidate, MatchResult
from .text import normalize_name
from .vcf_parser import ContactRecord, parse_vcf_contacts, parse_vcf_text
from .workbook import load_guest_workbook, write_output_workbook

__all__ = [
	"ContactRecord",
	"GuestRow",
	"MatchCandidate",
	"MatchResult",
	"load_guest_workbook",
	"match_guest_rows",
	"normalize_name",
	"parse_vcf_contacts",
	"parse_vcf_text",
	"__version__",
	"write_output_workbook",
]