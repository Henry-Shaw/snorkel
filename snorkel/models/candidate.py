from .meta import SnorkelSession, SnorkelBase
from .context import Context
from sqlalchemy import Table, Column, String, Integer, ForeignKey, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import relationship, backref
from sqlalchemy.types import PickleType


class CandidateSet(SnorkelBase):
    """A named collection of Candidate objects."""
    __tablename__ = 'candidate_set'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)

    def append(self, item):
        self.candidates.append(item)

    def remove(self, item):
        self.candidates.remove(item)

    def __eq__(self, other):
        return self is other

    def __ne__(self, other):
        return self is not other

    def __hash__(self):
        return id(self)

    def __iter__(self):
        """Default iterator is over Candidate objects"""
        for candidate in self.candidates:
            yield candidate

    def __len__(self):
        return len(self.candidates)

    def __getitem__(self, key):
        return self.candidates[key]

    def stats(self, gold_set=None):
        """Print diagnostic stats about CandidateSet."""
        session = SnorkelSession.object_session(self)

        # NOTE: This is the number of contexts that had non-zero number of candidates!
        nc = session.query(Context.id).join(Candidate).filter(CandidateSet.name == self.name).distinct().count()
        print "=" * 80
        print "%s candidates in %s contexts" % (self.__len__(), nc)
        print "Avg. # of candidates / context*: %0.1f" % (self.__len__() / float(nc),)
        if gold_set is not None:
            print "-" * 80
            print "Overlaps with %0.2f%% of gold set" % (len(gold_set.intersection(self)) / float(len(gold_set)),)
        print "=" * 80
        print "*Only counting contexts with non-zero number of candidates."

    def __repr__(self):
        return "Candidate Set (" + str(self.name) + ")"


class Candidate(SnorkelBase):
    """
    An abstract candidate relation.
    """
    __tablename__ = 'candidate'
    id = Column(Integer, primary_key=True)
    context_id = Column(Integer, ForeignKey('context.id'))
    candidate_set_id = Column(Integer, ForeignKey('candidate_set.id'))
    set = relationship('CandidateSet', backref=backref('candidates', cascade='all, delete-orphan'))
    type = Column(String, nullable=False)

    context = relationship('Context', backref=backref('candidates', cascade_backrefs=False))

    __table_args__ = (
        UniqueConstraint(id, candidate_set_id),
    )

    __mapper_args__ = {
        'polymorphic_identity': 'candidate',
        'polymorphic_on': type
    }


class TemporarySpan(object):

    def __init__(self, context=None, char_end=None, char_start=None, meta=None):
        self.context = context
        self.char_end = char_end
        self.char_start = char_start
        self.meta = meta

    def __len__(self):
        return self.char_end - self.char_start + 1

    def __eq__(self, other):
        try:
            return self.context == other.context and self.char_start == other.char_start and self.char_end == other.char_end
        except AttributeError:
            return False

    def __ne__(self, other):
        try:
            return self.context != other.context or self.char_start != other.char_start or self.char_end != other.char_end
        except AttributeError:
            return True

    def __hash__(self):
        return hash(self.context) + hash(self.char_start) + hash(self.char_end)

    def get_word_start(self):
        return self.char_to_word_index(self.char_start)

    def get_word_end(self):
        return self.char_to_word_index(self.char_end)

    def get_n(self):
        return self.get_word_end() - self.get_word_start() + 1

    def char_to_word_index(self, ci):
        """Given a character-level index (offset), return the index of the **word this char is in**"""
        i = None
        for i, co in enumerate(self.context.char_offsets):
            if ci == co:
                return i
            elif ci < co:
                return i-1
        return i

    def word_to_char_index(self, wi):
        """Given a word-level index, return the character-level index (offset) of the word's start"""
        return self.context.char_offsets[wi]

    def get_attrib_tokens(self, a):
        """Get the tokens of sentence attribute _a_ over the range defined by word_offset, n"""
        return self.context.__getattribute__(a)[self.get_word_start():self.get_word_end() + 1]

    def get_attrib_span(self, a, sep=" "):
        """Get the span of sentence attribute _a_ over the range defined by word_offset, n"""
        # NOTE: Special behavior for words currently (due to correspondence with char_offsets)
        if a == 'words':
            return self.context.text[self.char_start:self.char_end + 1]
        else:
            return sep.join(self.get_attrib_tokens(a))

    def get_span(self, sep=" "):
        return self.get_attrib_span('words', sep)

    def __contains__(self, other_span):
        return other_span.char_start >= self.char_start and other_span.char_end <= self.char_end

    def __getitem__(self, key):
        """
        Slice operation returns a new candidate sliced according to **char index**
        Note that the slicing is w.r.t. the candidate range (not the abs. sentence char indexing)
        """
        if isinstance(key, slice):
            char_start = self.char_start if key.start is None else self.char_start + key.start
            if key.stop is None:
                char_end = self.char_end
            elif key.stop >= 0:
                char_end = self.char_start + key.stop - 1
            else:
                char_end = self.char_end + key.stop
            return self._get_instance(char_start=char_start, char_end=char_end, context=self.context)
        else:
            raise NotImplementedError()

    def __repr__(self):
        return '%s("%s", context=%s, chars=[%s,%s], words=[%s,%s])' \
            % (self.__class__.__name__, self.get_span(), self.context.id, self.char_start, self.char_end,
               self.get_word_start(), self.get_word_end())

    def _get_instance(self, **kwargs):
        return TemporarySpan(**kwargs)

    def promote(self):
        return Span(context=self.context, char_start=self.char_start, char_end=self.char_end)


class Span(TemporarySpan, Candidate):
    """
    A span of characters, identified by Context id and character-index start, end (inclusive).

    char_offsets are **relative to the Context start**
    """
    __table__ = Table('span', SnorkelBase.metadata,
                      Column('id', Integer, primary_key=True),
                      Column('candidate_set_id', Integer),
                      Column('char_start', Integer),
                      Column('char_end', Integer),
                      Column('meta', PickleType),
                      ForeignKeyConstraint(['id', 'candidate_set_id'], ['candidate.id', 'candidate.candidate_set_id'])
                      )

    __table_args__ = (
        UniqueConstraint(__table__.c.candidate_set_id, __table__.c.context_id, __table__.c.char_start, __table__.c.char_end),
    )

    __mapper_args__ = {
        'polymorphic_identity': 'span',
    }

    def _get_instance(self, **kwargs):
        return Span(**kwargs)


class SpanPair(Candidate):
    """
    A pair of Span Candidates, representing a relation from Span 0 to Span 1.
    """
    __table__ = Table('span_pair', SnorkelBase.metadata,
                      Column('id', Integer, primary_key=True),
                      Column('candidate_set_id', Integer),
                      Column('span0_id', Integer),
                      Column('span1_id', Integer),
                      ForeignKeyConstraint(['id', 'candidate_set_id'], ['candidate.id', 'candidate.candidate_set_id']),
                      ForeignKeyConstraint(['span0_id'], ['span.id']),
                      ForeignKeyConstraint(['span1_id'], ['span.id'])
                      )

    __table_args__ = (
        UniqueConstraint(__table__.c.candidate_set_id, __table__.c.span0_id, __table__.c.span1_id),
    )

    span0 = relationship('Span', backref=backref('span_source_pairs', cascade_backrefs=False),
                          cascade_backrefs=False, foreign_keys='SpanPair.span0_id')
    span1 = relationship('Span', backref=backref('span_dest_pairs', cascade_backrefs=False),
                          cascade_backrefs=False, foreign_keys='SpanPair.span1_id')

    __mapper_args__ = {
        'polymorphic_identity': 'span_pair',
    }

    def __eq__(self, other):
        try:
            return self.span0 == other.span0 and self.span1 == other.span1
        except AttributeError:
            return False

    def __ne__(self, other):
        try:
            return self.span0 != other.span0 or self.span1 != other.span1
        except AttributeError:
            return True

    def __hash__(self):
        return hash(self.span0) + hash(self.span1)

    def __getitem__(self, key):
        if key == 0:
            return self.span0
        elif key == 1:
            return self.span1
        else:
            raise KeyError('Valid keys are 0 and 1.')

    def __repr__(self):
        return "SpanPair(%s, %s)" % (self.span0, self.span1)
