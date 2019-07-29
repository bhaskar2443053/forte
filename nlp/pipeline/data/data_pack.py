"""
This class defines the core interchange format, deals with basic operations
such as adding entries, getting data, and indexing.
"""
import logging
from collections import defaultdict
from typing import (DefaultDict, Dict, Iterable, Iterator, List, Optional,
                    Type, TypeVar, Union, Any, Set)

import numpy as np
from sortedcontainers import SortedList

from nlp.pipeline.data.ontology.base_ontology import Sentence
from nlp.pipeline.data.ontology import Entry, Annotation, Link, Group, Span

logger = logging.getLogger(__name__)

__all__ = [
    "Meta",
    "DataIndex",
    "DataPack",
]

E = TypeVar('E', bound=Entry)


class Meta:
    """
    Meta information of a datapack.
    """

    def __init__(self, doc_id: Optional[str] = None):
        self.doc_id = doc_id
        self.language = 'english'
        self.span_unit = 'character'
        self.process_state = ''
        self.cache_state = ''


class InternalMeta:
    """
    The internal meta information of **one kind of entry** in a datapack.
    Note that the :attr:`intertal_metas` in :class:`Datapack` is a dict in
    which the keys are entries names and the values are objects of
    :class:`InternalMeta`.
    """

    def __init__(self):
        self.id_counter = 0
        self.fields_created = defaultdict(set)
        self.default_component = None


class DataIndex:
    """
    A set of indexes used in a datapack: (1) :attr:`entry_index`,
    the index from each tid to the corresponding entry;
    (2) :attr:`type_index`, the index from each type to the entries of that
    type; (3) :attr:`component_index`, the index from each component to the
    entries generated by that component; (4) :attr:`link_index`, the index
    from child (:attr:`link_index["child_index"]`)and parent
    (:attr:`link_index["parent_index"]`) nodes to links; (5)
    :attr:`group_index`, the index from group members to groups.
    """

    def __init__(self, data_pack):
        self.data_pack: DataPack = data_pack
        # basic indexes (switches always on)
        self.entry_index: Dict[str, Entry] = dict()
        self.type_index: DefaultDict[Type, Set[str]] = defaultdict(set)
        self.component_index: DefaultDict[str, Set[str]] = defaultdict(set)
        # other indexes (built when first looked up)
        self._group_index = defaultdict(set)
        self._link_index: Dict[str, DefaultDict[str, set]] = dict()
        # indexing switches
        self._group_index_switch = False
        self._link_index_switch = False

    @property
    def link_index_switch(self):
        return self._link_index_switch

    def turn_link_index_switch(self, on: bool):
        self._link_index_switch = on

    @property
    def group_index_switch(self):
        return self._group_index_switch

    def turn_group_index_switch(self, on: bool):
        self._group_index_switch = on

    def link_index(self, tid: str, as_parent: bool = True) -> Set[str]:
        """
        Look up the link_index with key ``tid``.

        Args:
            tid (str): the tid of the entry being looked up.
            as_parent (bool): If `as_patent` is True, will look up
                :attr:`link_index["parent_index"] and return the tids of links
                whose parent is `tid`. Otherwise,  will look up
                :attr:`link_index["child_index"] and return the tids of links
                whose child is `tid`.
        """
        if not self._link_index_switch:
            self.update_link_index(self.data_pack.links)
        if as_parent:
            return self._link_index["parent_index"][tid]
        else:
            return self._link_index["child_index"][tid]

    def group_index(self, tid: str) -> Set[str]:
        """
        Look up the group_index with key `tid`.
        """
        if not self._group_index_switch:
            self.update_group_index(self.data_pack.groups)
        return self._group_index[tid]

    def in_span(self,
                inner_entry: Union[str, Entry],
                span: Span) -> bool:
        """Check whether the ``inner entry`` is within the given ``span``.
        Link entries are considered in a span if both the
        parent and the child are within the span. Group entries are
        considered in a span if all the members are within the span.

        Args:
            inner_entry (str or Entry): An :class:`Entry` object to be checked.
                We will check whether this entry is within ``span``.
            span (Span): A :class:`Span` object to be checked. We will check
                whether the ``inner_entry`` is within this span.
        """

        if isinstance(inner_entry, str):
            inner_entry = self.entry_index[inner_entry]

        if isinstance(inner_entry, Annotation):
            inner_begin = inner_entry.span.begin
            inner_end = inner_entry.span.end
        elif isinstance(inner_entry, Link):
            child = inner_entry.get_child()
            parent = inner_entry.get_parent()
            inner_begin = min(child.span.begin, parent.span.begin)
            inner_end = max(child.span.end, parent.span.end)
        elif isinstance(inner_entry, Group):
            inner_begin = -1
            inner_end = -1
            for mem in inner_entry.get_members():
                if inner_begin == -1:
                    inner_begin = mem.span.begin
                inner_begin = min(inner_begin, mem.span.begin)
                inner_end = max(inner_end, mem.span.end)
        else:
            raise ValueError(
                f"Invalid entry type {type(inner_entry)}. A valid entry "
                f"should be an instance of Annotation, Link, or Group."
            )
        return inner_begin >= span.begin and inner_end <= span.end

    def have_overlap(self,
                     entry1: Union[Annotation, str],
                     entry2: Union[Annotation, str]) -> bool:
        """Check whether the two annotations have overlap in span.

        Args:
            entry1 (str or Annotation): An :class:`Annotation` object to be
                checked, or the tid of the Annotation.
            entry2 (str or Annotation): Another :class:`Annotation` object to be
                checked, or the tid of the Annotation.
        """
        if isinstance(entry1, str):
            e = self.entry_index[entry1]
            if not isinstance(e, Annotation):
                raise TypeError(f"'entry1' should be an instance of Annotation,"
                                f" but get {type(e)}")
            entry1 = e

        if not isinstance(entry1, Annotation):
            raise TypeError(f"'entry1' should be an instance of Annotation,"
                            f" but get {type(entry1)}")

        if isinstance(entry2, str):
            e = self.entry_index[entry2]
            if not isinstance(e, Annotation):
                raise TypeError(f"'entry2' should be an instance of Annotation,"
                                f" but get {type(e)}")
            entry2 = e

        if not isinstance(entry2, Annotation):
            raise TypeError(f"'entry2' should be an instance of Annotation,"
                            f" but get {type(entry2)}")

        return not (entry1.span.begin >= entry2.span.end or
                    entry1.span.end <= entry2.span.begin)

    def update_basic_index(self, entries: List[Entry]):
        """Build or update the basic indexes, including (1) :attr:`entry_index`,
        the index from each tid to the corresponding entry;
        (2) :attr:`type_index`, the index from each type to the entries of that
        type; (3) :attr:`component_index`, the index from each component to the
        entries generated by that component.

        Args:
            entries (list): a list of entires to be added into the basic index.
        """
        for entry in entries:
            self.entry_index[entry.tid] = entry
            self.type_index[type(entry)].add(entry.tid)
            self.component_index[entry.component].add(entry.tid)

    def update_link_index(self, links: List[Link]):
        """Build or update :attr:`link_index`, the index from child and parent
        nodes to links. :attr:`link_index` consists of two sub-indexes:
        "child_index" is the index from child nodes to their corresponding
        links, and "parent_index" is the index from parent nodes to their
        corresponding links.

        Args:
            links (list): a list of links to be added into the index.
        """
        logger.debug("Updating link index")
        if not self.link_index_switch:
            self.turn_link_index_switch(on=True)
            self._link_index["child_index"] = defaultdict(set)
            self._link_index["parent_index"] = defaultdict(set)
            links = self.data_pack.links

        for link in links:
            self._link_index["child_index"][link.child].add(link.tid)
            self._link_index["parent_index"][link.parent].add(link.tid)

    def update_group_index(self, groups: List[Group]):
        """Build or update :attr:`group_index`, the index from group members
         to groups.

        Args:
            groups (list): a list of groups to be added into the index.
        """
        logger.debug("Updating group index")
        if not self.group_index_switch:
            self.turn_group_index_switch(on=True)
            self._group_index = defaultdict(set)
            groups = self.data_pack.groups

        for group in groups:
            for member in group.members:
                self._group_index[member].add(group.tid)


class DataPack:
    """
    A :class:`DataPack' contains a piece of natural language text and a
    collection of NLP entries (annotations, links, and groups). The natural
    language text could be a document, paragraph or in any other granularity.

    Args:
        doc_id (str, optional): A universal id of this ner_data pack.
    """

    def __init__(self, doc_id: Optional[str] = None):
        self._text = ""

        self.annotations: SortedList[Annotation] = SortedList()
        self.links: List[Link] = []
        self.groups: List[Group] = []

        self.index: DataIndex = DataIndex(self)

        self.meta: Meta = Meta(doc_id)
        self.internal_metas: \
            Dict[type, InternalMeta] = defaultdict(InternalMeta)

    def __getstate__(self):
        """
        In serialization, 1) will serialize the annotation sorted list as a
        normal list; 2) will not serialize the indexes
        """
        state = self.__dict__.copy()
        state['annotations'] = list(state['annotations'])
        del state['index']
        return state

    def __setstate__(self, state):
        """
        In deserialization, we 1) transform the annotation list back to a
        sorted list; 2) initialize the indexes.
        """
        self.__dict__.update(state)
        self.annotations = SortedList(self.annotations)
        self.index = DataIndex(self)
        self.index.update_basic_index(list(self.annotations))
        self.index.update_basic_index(self.links)
        self.index.update_basic_index(self.groups)

    @property
    def text(self):
        return self._text

    def set_text(self, text: str):
        if not text.startswith(self._text):
            logger.warning("The new text is overwriting the original one, "
                           "which might cause unexpected behavior.")
        self._text = text

    def add_or_get_entry(self, entry: E) -> E:
        """
        Try to add an :class:`Entry` object to the :class:`DataPack` object.
        If a same entry already exists, will return the existing annotation
        instead of adding the new one. Note that we regard two entries to be
        same if their :meth:`eq` have the same return value, and users could
        override :meth:`eq` in their custom entry classes.

        Args:
            entry (Entry): An :class:`Entry` object to be added to the datapack.

        Returns:
            If a same annotation already exists, returns the existing
            annotation. Otherwise, return the (input) annotation just added.
        """
        if isinstance(entry, Annotation):
            target = self.annotations
        elif isinstance(entry, Link):
            target = self.links
        elif isinstance(entry, Group):
            target = self.groups
        else:
            raise ValueError(
                f"Invalid entry type {type(entry)}. A valid entry "
                f"should be an instance of Annotation, Link, or Group."
            )

        if entry not in target:
            # add the entry to the target entry list
            name = entry.__class__
            entry.set_tid(str(self.internal_metas[name].id_counter))
            entry.attach(self)
            if isinstance(target, list):
                target.append(entry)
            else:
                target.add(entry)
            self.internal_metas[name].id_counter += 1

            # update the data pack index if needed
            self.index.update_basic_index([entry])
            if self.index.link_index_switch and isinstance(entry, Link):
                self.index.update_link_index([entry])
            if self.index.group_index_switch and isinstance(entry, Group):
                self.index.update_group_index([entry])

            return entry
        # logger.debug(f"Annotation already exist {annotation.tid}")
        return target[target.index(entry)]

    def add_entry(self, entry: E) -> E:
        """
        Force add an :class:`Entry` object to the :class:`DataPack` object.
        Allow duplicate entries in a datapack.

        Args:
            entry (Entry): An :class:`Entry` object to be added to the datapack.

        Returns:
            The input entry itself
        """
        if isinstance(entry, Annotation):
            target = self.annotations
        elif isinstance(entry, Link):
            target = self.links
        elif isinstance(entry, Group):
            target = self.groups
        else:
            raise ValueError(
                f"Invalid entry type {type(entry)}. A valid entry "
                f"should be an instance of Annotation, Link, or Group."
            )

        # add the entry to the target entry list
        entry.set_tid(str(self.internal_metas[entry.__class__].id_counter))
        entry.attach(self)
        if isinstance(target, list):
            target.append(entry)
        else:
            target.add(entry)
        self.internal_metas[entry.__class__].id_counter += 1

        # update the data pack index if needed
        self.index.update_basic_index([entry])
        if self.index.link_index_switch and isinstance(entry, Link):
            self.index.update_link_index([entry])
        if self.index.group_index_switch and isinstance(entry, Group):
            self.index.update_group_index([entry])

        return entry

    def record_fields(self, fields: List[str], entry_type: Type[Entry],
                      component: str):
        """Record in the internal meta that ``component`` has generated
        ``fields`` for ``entry_type``.
        """
        if entry_type not in self.internal_metas.keys() or \
                self.internal_metas[entry_type].default_component is None:
            self.internal_metas[entry_type].default_component = component

        fields.append("tid")
        for field in fields:
            self.internal_metas[entry_type].fields_created[component].add(field)

    def set_meta(self, **kwargs):
        for k, v in kwargs.items():
            if not hasattr(self.meta, k):
                raise AttributeError(f"Meta has no attribute named {k}")
            setattr(self.meta, k, v)

    def get_data(
            self,
            context_type: str,
            requests: Optional[Dict[Type[Entry], Union[Dict, List]]] = None,
            offset: int = 0
    ) -> Iterator[Dict[str, Any]]:
        """
        Example:

            .. code-block:: python

                requests = {
                    base_ontology.Sentence:
                        {
                            "component": ["dummy"],
                            "fields": ["speaker"],
                        },
                    base_ontology.Token: ["pos_tag", "sense""],
                    base_ontology.EntityMention: {
                        "unit": "Token",
                    },
                }
                pack.get_data("sentence", requests)

        Args:
            context_type (str): The granularity of the ner_data context, which
                could be either `"sentence"` or `"document"`
            requests (dict): The entry types and fields required.
                The keys of the dict are the required entry types and the
                value should be either a list of field names or a dict.
                If the value is a dict, accepted items includes "fields",
                "component", and "unit". By setting "component" (a list), users
                can specify the components by which the entires are generated.
                If "component" is not specified, will return entries generated
                by all components. By setting "unit" (a string), users can
                specify a unit by which the annotations are indexed.
                Note that for all annotations, "text" and "span" fields are
                given by default; for all links, "child" and "parent"
                fields are given by default.
            offset (int): Will skip the first `offset` instances and generate
                ner_data from the `offset` + 1 instance.
        Returns:
            A ner_data generator, which generates one piece of ner_data (a dict
            containing the required annotations and context).
        """
        annotation_types: Dict[Type[Annotation], Union[Dict, List]] = dict()
        link_types: Dict[Type[Link], Union[Dict, List]] = dict()
        group_types: Dict[Type[Group], Union[Dict, List]] = dict()
        if requests is not None:
            for key, value in requests.items():
                if issubclass(key, Annotation):
                    annotation_types[key] = value
                elif issubclass(key, Link):
                    link_types[key] = value
                elif issubclass(key, Group):
                    group_types[key] = value

        if context_type.lower() == "document":
            data: Dict[str, Any] = dict()
            data["context"] = self.text
            data["offset"] = 0

            if annotation_types:
                for a_type, a_args in annotation_types.items():
                    if a_type.__name__ in data.keys():
                        raise KeyError(
                            f"Requesting two types of entries with the same "
                            f"class name {a_type.__name__} at the same time is "
                            f"not allowed")
                    data[a_type.__name__] = \
                        self._generate_annotation_entry_data(
                            a_type, a_args, data, None
                        )

            if link_types:
                for l_type, l_args in link_types.items():
                    if l_type.__name__ in data.keys():
                        raise KeyError(
                            f"Requesting two types of entries with the same "
                            f"class name {l_type.__name__} at the same time is "
                            f"not allowed")
                    data[l_type.__name__] = self._generate_link_entry_data(
                        l_type, l_args, data, None
                    )

            if group_types:
                for g_type, g_args in group_types.items():  # pylint: disable=unused-variable
                    pass

            yield data

        elif context_type.lower() == "sentence":
            sent_type = Sentence
            sent_args = None
            if annotation_types:
                has_sentence_args = False
                for a_type, a_args in annotation_types.items():
                    if issubclass(a_type, Sentence):
                        if has_sentence_args:
                            raise KeyError(
                                f'At most one sentence request is allowed, '
                                f'but got {sent_type} and {a_type} at the '
                                f'same time.')
                        has_sentence_args = True
                        sent_type = a_type
                        sent_args = a_args

            sent_components, _, sent_fields = self._parse_request_args(
                sent_type, sent_args
            )

            valid_sent_ids = self.get_ids_by_type(Sentence)
            if sent_components:
                valid_component_id: Set[str] = set()
                for component in sent_components:
                    valid_component_id |= self.get_ids_by_compoent(component)
                valid_sent_ids &= valid_component_id

            skipped = 0
            # must iterate through a copy here
            for sent in list(self.annotations):
                if (sent.tid not in valid_sent_ids or
                        not isinstance(sent, sent_type)):
                    continue
                if skipped < offset:
                    skipped += 1
                    continue

                data = dict()
                data["context"] = self.text[sent.span.begin: sent.span.end]
                data["offset"] = sent.span.begin

                for field in sent_fields:
                    data[field] = getattr(sent, field)

                if annotation_types:
                    for a_type, a_args in annotation_types.items():
                        if issubclass(a_type, Sentence):
                            continue
                        if a_type.__name__ in data.keys():
                            raise KeyError(
                                f"Requesting two types of entries with the "
                                f"same class name {a_type.__name__} at the "
                                f"same time is not allowed")
                        data[a_type.__name__] = \
                            self._generate_annotation_entry_data(
                                a_type, a_args, data, sent
                            )
                if link_types:
                    for l_type, l_args in link_types.items():
                        if l_type.__name__ in data.keys():
                            raise KeyError(
                                f"Requesting two types of entries with the "
                                f"same class name {l_type.__name__} at the "
                                f"same time is not allowed")
                        data[l_type.__name__] = self._generate_link_entry_data(
                            l_type, l_args, data, sent
                        )

                if group_types:
                    for g_type, g_args in group_types.items():  # pylint: disable=unused-variable
                        pass

                yield data

    def _parse_request_args(self, a_type, a_args):
        # request which fields generated by which component
        components = None
        unit = None
        fields = set()
        if isinstance(a_args, dict):
            components = a_args.get("component")
            if components is not None and not isinstance(components, Iterable):
                raise TypeError(
                    f"Invalid request format for 'components'. "
                    f"The value of 'components' should be of an iterable type."
                )
            unit = a_args.get("unit")
            if unit is not None and not isinstance(unit, str):
                raise TypeError(
                    f"Invalid request format for 'unit'. "
                    f"The value of 'unit' should be a string."
                )
            a_args = a_args.get("fields", set())

        if isinstance(a_args, Iterable):
            fields = set(a_args)
        elif a_args is not None:
            raise TypeError(
                f"Invalid request format for '{a_type}'. "
                f"The request should be of an iterable type or a dict."
            )

        # check the existence of fields
        for meta_key, meta_val in self.internal_metas.items():
            if issubclass(meta_key, a_type):
                for meta_c, meta_f in meta_val.fields_created.items():
                    if components is None or meta_c in components:
                        if not fields.issubset(meta_f):
                            raise KeyError(
                                f"The {a_type} generated by {meta_c} doesn't "
                                f"have the fields requested.")

        fields.add("tid")
        return components, unit, fields

    def _generate_annotation_entry_data(
            self,
            a_type: Type[Annotation],
            a_args: Union[Dict, Iterable],
            data: Dict,
            sent: Optional[Sentence]) -> Dict:

        components, unit, fields = self._parse_request_args(a_type, a_args)

        a_dict: Dict[str, Any] = dict()

        a_dict["span"] = []
        a_dict["text"] = []
        for field in fields:
            a_dict[field] = []

        unit_begin = 0
        if unit is not None:
            if unit not in data.keys():
                raise KeyError(f"{unit} is missing in data. You need to "
                               f"request {unit} before {a_type}.")
            a_dict["unit_span"] = []

        sent_begin = sent.span.begin if sent else 0
        annotations = self.get_entries(a_type, sent, components)

        for annotation in annotations:
            # we provide span, text (and also tid) by default
            a_dict["span"].append((annotation.span.begin,
                                   annotation.span.end))
            a_dict["text"].append(annotation.text)

            for field in fields:
                if field in ("span", "text"):
                    continue
                if field == "context_span":
                    a_dict[field].append((annotation.span.begin - sent_begin,
                                          annotation.span.end - sent_begin))
                    continue

                a_dict[field].append(getattr(annotation, field))

            if unit is not None:
                while not self.index.in_span(data[unit]["tid"][unit_begin],
                                             annotation.span):
                    unit_begin += 1

                unit_span_begin = unit_begin
                unit_span_end = unit_span_begin + 1

                while self.index.in_span(data[unit]["tid"][unit_span_end],
                                         annotation.span):
                    unit_span_end += 1

                a_dict["unit_span"].append((unit_span_begin, unit_span_end))

        for key, value in a_dict.items():
            a_dict[key] = np.array(value)

        return a_dict

    def _generate_link_entry_data(
            self,
            a_type: Type[Link],
            a_args: Union[Dict, Iterable],
            data: Dict,
            sent: Optional[Sentence]) -> Dict:

        components, unit, fields = self._parse_request_args(a_type, a_args)

        if unit is not None:
            raise ValueError(f"Link entires cannot be indexed by {unit}.")

        a_dict: Dict[str, Any] = dict()
        for field in fields:
            a_dict[field] = []
        a_dict["parent"] = []
        a_dict["child"] = []

        links = self.get(a_type, sent, components)

        for link in links:
            parent_type = link.parent_type.__name__
            child_type = link.child_type.__name__

            if parent_type not in data.keys():
                raise KeyError(f"The Parent entry of {a_type} is not requested."
                               f" You should also request {parent_type} with "
                               f"{a_type}")
            if child_type not in data.keys():
                raise KeyError(f"The child entry of {a_type} is not requested."
                               f" You should also request {child_type} with "
                               f"{a_type}")

            a_dict["parent"].append(
                np.where(data[parent_type]["tid"] == link.parent)[0][0])
            a_dict["child"].append(
                np.where(data[child_type]["tid"] == link.child)[0][0])

            for field in fields:
                if field in ("parent", "child"):
                    continue

                a_dict[field].append(getattr(link, field))

        for key, value in a_dict.items():
            a_dict[key] = np.array(value)
        return a_dict

    def get_entries(self,
                    entry_type: Type[E],
                    range_annotation: Optional[Annotation] = None,
                    components: Optional[Union[str, List[str]]] = None
                    ) -> Iterable[E]:
        """
        Get ``entry_type`` entries from the span of ``range_annotation`` in a
        DataPack.

        Args:
            entry_type (type): The type of entries requested.
            range_annotation (Annotation, optional): The range of entries
                requested. If `None`, will return valid entries in the range of
                whole data_pack.
            components (str or list, optional): The component generating the
                entries requested. If `None`, will return valid entries
                generated by any component.
        """
        range_begin = range_annotation.span.begin if range_annotation else 0
        range_end = (range_annotation.span.end if range_annotation else
                     self.annotations[-1].span.end)

        # ``a_type`` annotations generated by ``component`` in ``range``
        valid_id = self.get_ids_by_type(entry_type)
        if components is not None:
            if isinstance(components, str):
                components = [components]
            valid_component_id: Set[str] = set()
            for component in components:
                valid_component_id |= self.get_ids_by_compoent(component)
            valid_id &= valid_component_id

        if issubclass(entry_type, Annotation):
            begin_index = self.annotations.bisect(
                Annotation(range_begin, -1))
            end_index = self.annotations.bisect(Annotation(range_end, -1))
            for annotation in self.annotations[begin_index: end_index]:
                if annotation.tid not in valid_id:
                    continue
                if (range_annotation is None or
                        self.index.in_span(annotation, range_annotation.span)):
                    yield annotation

        elif issubclass(entry_type, (Link, Group)):
            for entry_id in valid_id:
                entry = self.get_entry_by_id(entry_id)
                if (range_annotation is None or
                        self.index.in_span(entry, range_annotation.span)):
                    yield entry

    def get(self,
            entry_type: Type[E],
            range_annotation: Optional[Annotation] = None,
            component: Optional[str] = None) -> Iterable[E]:
        return self.get_entries(entry_type, range_annotation, component)

    def get_entry_by_id(self, tid: str):
        """
        Look up the entry_index with key ``tid``.
        """
        entry = self.index.entry_index.get(tid)
        if entry is None:
            raise KeyError(
                f"There is no entry with tid '{tid}'' in this datapack")
        return entry

    def get_ids_by_compoent(self, component: str) -> Set[str]:
        """
        Look up the component_index with key ``component``.
        """
        entry_set = self.index.component_index[component]
        if len(entry_set) == 0:
            logging.warning("There is no entry generated by '%s' "
                            "in this datapack", component)
        return entry_set

    def get_entries_by_compoent(self, component: str) -> Set[Entry]:
        return {self.get_entry_by_id(tid)
                    for tid in self.get_ids_by_compoent(component)}

    def get_ids_by_type(self, tp: Type[E]) -> Set[str]:
        """
        Look up the type_index with key ``tp``.

        Returns:
             A set of entry tids. The entries are instances of tp (and also
             includes instances of the subclasses of tp).
        """
        subclass_index = set()
        for index_key, index_val in self.index.type_index.items():
            if issubclass(index_key, tp):
                subclass_index.update(index_val)

        if len(subclass_index) == 0:
            logging.warning("There is no %s type entry in this datapack", tp)
        return subclass_index

    def get_entries_by_type(self, tp: Type[E]) -> Set[E]:
        entries: Set = set()
        for tid in self.get_ids_by_type(tp):
            entry = self.get_entry_by_id(tid)
            if isinstance(entry, tp):
                entries.add(entry)
        return entries

    def get_links_by_parent(self, parent: Union[str, Entry]) -> Set[Link]:
        links = set()
        if isinstance(parent, Entry):
            tid = parent.tid
            if tid is None:
                raise ValueError(f"Argument parent has no tid. "
                                 f"Have you add this entry into the datapack?")
        else:
            tid = parent
        for tid in self.index.link_index(tid, as_parent=True):
            entry = self.get_entry_by_id(tid)
            if isinstance(entry, Link):
                links.add(entry)
        return links

    def get_links_by_child(self, child: Union[str, Entry]) -> Set[Link]:
        links = set()
        if isinstance(child, Entry):
            tid = child.tid
            if tid is None:
                raise ValueError(f"Argument child has no tid. "
                                 f"Have you add this entry into the datapack?")
        else:
            tid = child
        for tid in self.index.link_index(tid, as_parent=False):
            entry = self.get_entry_by_id(tid)
            if isinstance(entry, Link):
                links.add(entry)
        return links

    def get_groups_by_member(self, member: Union[str, Entry]) -> Set[Group]:
        groups = set()
        if isinstance(member, Entry):
            tid = member.tid
            if tid is None:
                raise ValueError(f"Argument member has no tid. "
                                 f"Have you add this entry into the datapack?")
        else:
            tid = member
        for tid in self.index.group_index(tid):
            entry = self.get_entry_by_id(tid)
            if isinstance(entry, Group):
                groups.add(entry)
        return groups
