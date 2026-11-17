from unittest.mock import Mock
import pytest
from kafka import TopicPartition
from bi_platform_shared.cdc_contract import CdcError
from shared.cdc.worker import ResumeOffsets


@pytest.mark.parametrize('committed,checkpoint,begin,end,expected',[
    (None,None,0,10,0), (6,None,0,10,6), (None,{'offset':5},0,10,6),
    (6,{'offset':7},0,10,6), (10,None,0,10,10),
])
def test_resume_from_durable_position(committed,checkpoint,begin,end,expected):
    p=TopicPartition('scope',0)
    consumer=Mock()
    consumer.beginning_offsets.return_value={p:begin}
    consumer.end_offsets.return_value={p:end}
    consumer.committed.return_value=committed
    ResumeOffsets(consumer,'load',{'load:0':checkpoint} if checkpoint else {}).on_partitions_assigned([p])
    consumer.seek.assert_called_once_with(p,expected)


@pytest.mark.parametrize('committed,begin,end',[(1,2,10),(None,2,10),(15,0,10)])
def test_retention_gap_never_silently_resets(committed,begin,end):
    p=TopicPartition('scope',0)
    consumer=Mock()
    consumer.beginning_offsets.return_value={p:begin}
    consumer.end_offsets.return_value={p:end}
    consumer.committed.return_value=committed
    with pytest.raises(CdcError,match='RETENTION_LOST'):
        ResumeOffsets(consumer,'load',{}).on_partitions_assigned([p])
    consumer.seek.assert_not_called()


def test_expired_heartbeat_does_not_reset_business_checkpoint():
    p=TopicPartition('__debezium-heartbeat.scope',0)
    consumer=Mock()
    consumer.beginning_offsets.return_value={p:20}
    consumer.end_offsets.return_value={p:30}
    consumer.committed.return_value=10
    ResumeOffsets(consumer,'normalize',{'normalize:0':{'offset':100}},p.topic).on_partitions_assigned([p])
    consumer.seek.assert_called_once_with(p,20)


def test_notification_retention_gap_fails_closed():
    p = TopicPartition('scope.notification', 0)
    consumer = Mock()
    consumer.beginning_offsets.return_value = {p: 9}
    consumer.end_offsets.return_value = {p: 20}
    consumer.committed.return_value = None
    with pytest.raises(CdcError, match='RETENTION_LOST'):
        ResumeOffsets(consumer, 'normalize', {}, notification_topic=p.topic,
                      notification_offset=4).on_partitions_assigned([p])
    consumer.seek.assert_not_called()
