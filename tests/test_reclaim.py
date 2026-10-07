import pytest

from vgpu_local.contracts.models import InterruptionScope
from vgpu_local.errors import KeyConflict, OutcomeUnknown
from vgpu_local.interruptions import InterruptionController
from vgpu_local.journal import Journal
from vgpu_local.reclaim import LocalReclaimer
from vgpu_local.simulator import Simulator, Faults
from test_interruptions import source, request as response


class Backend:
    def __init__(self, journal):
        self.engine = Simulator(journal)
        self.observes = self.releases = 0
        self.lost_reply = False
        self.override = None
        self.on_release = None

    def observe(self, request):
        self.observes += 1
        return self.override or self.engine.observe(request)

    def release(self, request):
        self.releases += 1
        if self.on_release: self.on_release()
        result = self.engine.release(request)
        if self.lost_reply:
            self.lost_reply = False
            raise OutcomeUnknown('reply lost after teardown')
        return result


@pytest.fixture
def setup(tmp_path, backend_request):
    journal = Journal(tmp_path/'state.db')
    backend = Backend(journal)
    observed = backend.engine.provision(backend_request)
    runtime = InterruptionScope(tenant_id=backend_request.tenant_id,project_id=backend_request.project_id,generation=1,
        lease_id='lease-a',job_id='job-a',attempt_id='attempt-a',controller_epoch=1,agent_session_id='igs_'+'a'*32)
    book = InterruptionController(journal,runtime,['rank-0','rank-1'])
    reclaimer = LocalReclaimer(book,backend,backend_request,observed.resource_id)
    return book,backend,reclaimer,backend_request,observed


def ready(book, notice, participant):
    return book.respond(response(notice,participant,'ready'),participant_id=participant)


def test_ack_and_partial_readiness_never_release_but_all_expected_participants_can(setup):
    book,backend,reclaimer,request,observed = setup
    notice = book.publish(source())
    book.respond(response(notice),participant_id='rank-0')
    assert reclaimer.step(2000)['state'] == 'waiting'
    ready(book,notice,'rank-0')
    assert reclaimer.step(2000)['state'] == 'waiting'
    assert backend.observes == backend.releases == 0
    ready(book,notice,'rank-1')
    assert reclaimer.step(2000)['state'] == 'completed'
    assert backend.releases == 1
    assert book.snapshot().interruptions[0].phase == 'completed'
    assert reclaimer.step(9000)['observation']['supplier_state'] == 'released'
    assert backend.releases == 1


def test_known_stop_time_can_reclaim_without_any_response(setup):
    book,backend,reclaimer,_,_ = setup
    book.publish(source())
    assert reclaimer.step(4499)['state'] == 'waiting'
    assert reclaimer.step(4500)['state'] == 'completed'
    assert backend.releases == 1


@pytest.mark.parametrize('advisory',[False,True])
def test_unknown_time_or_advisory_never_invents_a_reclaim_deadline(setup,advisory):
    book,backend,reclaimer,_,_ = setup
    book.publish(source(kind='advisory' if advisory else 'preempt',release_by_ms=None,signal_at_ms=None,
                        extension_limit_ms=None,allowed_actions=['ack'] if advisory else ['ack','ready']))
    assert reclaimer.step(999999)['state'] == 'waiting'
    assert backend.observes == backend.releases == 0


@pytest.mark.parametrize('withdraw',[False,True])
def test_withdrawal_or_explicit_extension_supersedes_the_old_stop_time(setup,withdraw):
    book,backend,reclaimer,_,_ = setup
    notice = book.publish(source())
    if withdraw: book.publish(source(source_revision=2,state='withdrawn'))
    else:
        extension = response(notice,action='request_extension',requested_release_by_ms=8000)
        book.respond(extension,participant_id='rank-0')
        book.grant_extension(extension.request_id,notice.version)
    assert reclaimer.step(4500)['state'] == 'waiting'
    assert backend.releases == 0
    if not withdraw: assert reclaimer.step(7500)['state'] == 'completed'


def test_restarts_after_lost_teardown_reply_by_observing_without_a_second_delete(setup):
    book,backend,reclaimer,request,observed = setup
    book.publish(source())
    backend.lost_reply = True
    with pytest.raises(OutcomeUnknown): reclaimer.step(4500)
    assert book.snapshot().interruptions[0].phase == 'releasing'
    restarted = LocalReclaimer(book,backend,request,observed.resource_id)
    assert restarted.step(4501)['state'] == 'completed'
    assert backend.releases == 1


def test_failed_teardown_stays_releasing_and_retries_the_same_allocation(setup):
    book,backend,reclaimer,request,_ = setup
    book.publish(source())
    backend.engine.faults = Faults(fail_teardown=True)
    with pytest.raises(OutcomeUnknown): reclaimer.step(4500)
    assert book.snapshot().interruptions[0].phase == 'releasing'
    assert backend.engine.observe(request).supplier_state == 'allocated'
    backend.engine.faults = Faults()
    assert reclaimer.step(4501)['state'] == 'completed'


@pytest.mark.parametrize('change',[{'resource_id':'foreign'},{'project_id':'foreign'},{'generation':2},
                                  {'state':'unknown','supplier_state':'unknown'}],ids=['resource','project','generation','unknown'])
def test_ambiguous_or_foreign_resource_evidence_prevents_teardown(setup,change):
    book,backend,reclaimer,_,observed = setup
    book.publish(source())
    backend.override = observed.model_copy(update=change)
    with pytest.raises(OutcomeUnknown): reclaimer.step(4500)
    assert backend.releases == 0
    assert book.snapshot().interruptions[0].phase == 'releasing'


def test_runtime_binding_is_immutable_and_missing_notice_history_cannot_be_recreated(setup,tmp_path):
    book,backend,reclaimer,request,observed = setup
    with pytest.raises(KeyConflict): LocalReclaimer(book,backend,request,'foreign')
    with pytest.raises(KeyConflict): LocalReclaimer(book,backend,request.model_copy(update={'account_id':'other'}),observed.resource_id)
    with pytest.raises(ValueError): LocalReclaimer(book,backend,request.model_copy(update={'project_id':'other'}),observed.resource_id)
    with pytest.raises(KeyError): InterruptionController(Journal(tmp_path/'empty.db'),book.scope,['rank-0','rank-1'],existing_only=True)
    assert backend.observes == backend.releases == 0


def test_late_withdrawal_does_not_undo_committed_reclaim(setup):
    book,backend,reclaimer,_,_ = setup
    book.publish(source())
    backend.on_release = lambda: book.publish(source(source_revision=2,state='withdrawn'))
    assert reclaimer.step(4500)['state'] == 'completed'
    assert backend.releases == 1
    assert book.snapshot().interruptions[0].phase == 'completed'


def test_late_backend_observation_cannot_advance_or_repeat_teardown(setup):
    book,backend,reclaimer,_,observed = setup
    book.publish(source())
    backend.engine.faults = Faults(fail_teardown=True)
    backend.override = observed.model_copy(update={'revision':4})
    with pytest.raises(OutcomeUnknown): reclaimer.step(4500)
    assert backend.releases == 1
    backend.override = observed.model_copy(update={'revision':3})
    with pytest.raises(OutcomeUnknown,match='late backend'): reclaimer.step(4501)
    assert backend.releases == 1
