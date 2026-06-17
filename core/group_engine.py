"""Group engine - groups images by MD5 and creates Group objects."""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple
import uuid

from core.scanner import ImageFile


@dataclass
class Group:
    """Represents a group of images with the same MD5."""
    id: str
    images: List[ImageFile]
    keep: ImageFile = None
    duplicates: List[ImageFile] = field(default_factory=list)


def group_by_md5(images: List[ImageFile]) -> List[Group]:
    """Group images by MD5 hash.

    Only images with non-empty MD5 are included.

    Args:
        images: List of ImageFile objects with MD5 computed

    Returns:
        List of Group objects
    """
    md5_map: Dict[str, List[ImageFile]] = {}
    for img in images:
        if not img.md5:
            continue
        if img.md5 not in md5_map:
            md5_map[img.md5] = []
        md5_map[img.md5].append(img)

    groups: List[Group] = []
    for md5, imgs in md5_map.items():
        group = Group(
            id=str(uuid.uuid4())[:8],
            images=imgs,
        )
        groups.append(group)

    return groups


def split_groups(groups: List[Group]) -> Tuple[List[Group], List[Group]]:
    """Split groups into single-image and multi-image groups.

    Args:
        groups: List of Group objects

    Returns:
        Tuple of (single_groups, multi_groups)
    """
    single_groups: List[Group] = []
    multi_groups: List[Group] = []

    for group in groups:
        if len(group.images) == 1:
            single_groups.append(group)
        else:
            multi_groups.append(group)

    return single_groups, multi_groups
