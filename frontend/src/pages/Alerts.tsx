import { useEffect, useState } from 'react'
import {
  Table, Tag, Button, Tabs, Modal, Form, Input, Select, Switch,
  InputNumber, Space, Popconfirm, message, Badge,
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, BellOutlined } from '@ant-design/icons'
import client from '../api/client'

const SEVERITY_OPTIONS = [
  { label: '严重', value: 'critical' },
  { label: '警告', value: 'warning' },
  { label: '信息', value: 'info' },
]

const ALERT_TYPE_OPTIONS = [
  { label: '阈值告警', value: 'threshold' },
  { label: '异常检测', value: 'anomaly' },
  { label: '趋势预测', value: 'prediction' },
]

const OPERATOR_OPTIONS = [
  { label: '大于 (>)', value: '>' },
  { label: '大于等于 (>=)', value: '>=' },
  { label: '小于 (<)', value: '<' },
  { label: '小于等于 (<=)', value: '<=' },
  { label: '等于 (==)', value: '==' },
]

const CHANNEL_TYPES = [
  { label: '飞书', value: 'feishu' },
  { label: '企业微信', value: 'wechat' },
  { label: '邮件', value: 'email' },
  { label: 'Webhook', value: 'webhook' },
]

function Alerts() {
  const [events, setEvents] = useState<any[]>([])
  const [rules, setRules] = useState<any[]>([])
  const [channels, setChannels] = useState<any[]>([])
  const [devices, setDevices] = useState<any[]>([])
  const [metricDefs, setMetricDefs] = useState<any[]>([])

  const [ruleModalOpen, setRuleModalOpen] = useState(false)
  const [editingRule, setEditingRule] = useState<any>(null)
  const [ruleForm] = Form.useForm()

  const [channelModalOpen, setChannelModalOpen] = useState(false)
  const [editingChannel, setEditingChannel] = useState<any>(null)
  const [channelForm] = Form.useForm()
  const [channelType, setChannelType] = useState<string>('feishu')

  const [alertType, setAlertType] = useState<string>('threshold')

  const loadData = () => {
    client.get('/alerts/events').then(res => setEvents(res.data.items))
    client.get('/alerts/rules').then(res => setRules(res.data.items))
    client.get('/notifications/channels').then(res => setChannels(res.data.items))
    client.get('/devices').then(res => setDevices(res.data.items))
    client.get('/metrics/definitions').then(res => setMetricDefs(res.data.items))
  }

  useEffect(() => { loadData() }, [])

  const severityColor = (s: string) => {
    switch (s) {
      case 'critical': return 'red'
      case 'warning': return 'orange'
      default: return 'blue'
    }
  }

  const severityLabel = (s: string) => {
    switch (s) {
      case 'critical': return '严重'
      case 'warning': return '警告'
      default: return '信息'
    }
  }

  const statusLabel = (s: string) => {
    switch (s) {
      case 'firing': return '触发中'
      case 'resolved': return '已恢复'
      case 'acknowledged': return '已确认'
      default: return s
    }
  }

  const deviceName = (id: string) => devices.find((d: any) => d.id === id)?.name || id.slice(0, 8)

  // --- Alert Events ---
  const acknowledge = async (id: string) => {
    await client.post(`/alerts/events/${id}/acknowledge`)
    message.success('已确认')
    loadData()
  }

  const eventColumns = [
    {
      title: '时间', dataIndex: 'triggered_at', key: 'triggered_at', width: 180,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    { title: '设备', dataIndex: 'device_id', key: 'device_id', render: (id: string) => deviceName(id) },
    {
      title: '指标', dataIndex: 'metric_name', key: 'metric_name',
      render: (name: string) => metricDefs.find((m: any) => m.name === name)?.display_name || name,
    },
    { title: '级别', dataIndex: 'severity', key: 'severity', render: (s: string) => <Tag color={severityColor(s)}>{severityLabel(s)}</Tag> },
    {
      title: '状态', dataIndex: 'status', key: 'status',
      render: (s: string) => {
        const color = s === 'firing' ? 'red' : s === 'resolved' ? 'green' : 'default'
        return <Tag color={color}>{statusLabel(s)}</Tag>
      },
    },
    { title: '消息', dataIndex: 'message', key: 'message', ellipsis: true },
    {
      title: '操作', key: 'action', width: 80,
      render: (_: any, record: any) => record.status === 'firing' ? (
        <Button size="small" onClick={() => acknowledge(record.id)}>确认</Button>
      ) : null,
    },
  ]

  // --- Alert Rules ---
  const openRuleModal = (rule?: any) => {
    setEditingRule(rule || null)
    if (rule) {
      setAlertType(rule.type)
      ruleForm.setFieldsValue({
        name: rule.name,
        metric_name: rule.metric_name,
        device_ids: rule.device_ids,
        type: rule.type,
        severity: rule.severity,
        notification_channel_ids: rule.notification_channel_ids,
        enabled: rule.enabled,
        operator: rule.condition?.operator,
        threshold_value: rule.condition?.value,
        duration: rule.condition?.duration || 300,
        z_threshold: rule.condition?.z_threshold || 3.0,
        lookback_hours: rule.condition?.lookback_hours || 24,
        predict_hours: rule.condition?.predict_hours || 24,
        capacity: rule.condition?.capacity || 100,
        lookback_days: rule.condition?.lookback_days || 7,
      })
    } else {
      setAlertType('threshold')
      ruleForm.resetFields()
      ruleForm.setFieldsValue({ type: 'threshold', severity: 'warning', enabled: true, duration: 300 })
    }
    setRuleModalOpen(true)
  }

  const saveRule = async () => {
    const values = await ruleForm.validateFields()
    let condition: any = {}
    if (values.type === 'threshold') {
      condition = { operator: values.operator, value: values.threshold_value, duration: values.duration }
    } else if (values.type === 'anomaly') {
      condition = { z_threshold: values.z_threshold, lookback_hours: values.lookback_hours }
    } else if (values.type === 'prediction') {
      condition = { predict_hours: values.predict_hours, capacity: values.capacity, lookback_days: values.lookback_days }
    }

    const payload = {
      name: values.name,
      metric_name: values.metric_name,
      device_ids: values.device_ids || [],
      type: values.type,
      condition,
      severity: values.severity,
      notification_channel_ids: values.notification_channel_ids || [],
      enabled: values.enabled,
    }

    if (editingRule) {
      await client.put(`/alerts/rules/${editingRule.id}`, payload)
      message.success('规则已更新')
    } else {
      await client.post('/alerts/rules', payload)
      message.success('规则已创建')
    }
    setRuleModalOpen(false)
    loadData()
  }

  const deleteRule = async (id: string) => {
    await client.delete(`/alerts/rules/${id}`)
    message.success('规则已删除')
    loadData()
  }

  const toggleRule = async (rule: any) => {
    await client.put(`/alerts/rules/${rule.id}`, { enabled: !rule.enabled })
    loadData()
  }

  const ruleColumns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    {
      title: '指标', dataIndex: 'metric_name', key: 'metric_name',
      render: (name: string) => metricDefs.find((m: any) => m.name === name)?.display_name || name,
    },
    {
      title: '类型', dataIndex: 'type', key: 'type',
      render: (t: string) => ALERT_TYPE_OPTIONS.find(o => o.value === t)?.label || t,
    },
    {
      title: '条件', dataIndex: 'condition', key: 'condition',
      render: (cond: any, record: any) => {
        if (record.type === 'threshold') return `${cond.operator} ${cond.value} (${cond.duration}s均值)`
        if (record.type === 'anomaly') return `Z-score > ${cond.z_threshold}`
        if (record.type === 'prediction') return `预测${cond.predict_hours}h达${cond.capacity}`
        return '-'
      },
    },
    {
      title: '设备', dataIndex: 'device_ids', key: 'device_ids',
      render: (ids: string[]) => ids?.length ? ids.map((id: string) => deviceName(id)).join(', ') : '全部',
    },
    { title: '级别', dataIndex: 'severity', key: 'severity', render: (s: string) => <Tag color={severityColor(s)}>{severityLabel(s)}</Tag> },
    {
      title: '通知', dataIndex: 'notification_channel_ids', key: 'channels',
      render: (ids: string[]) => ids?.length ? ids.map((id: string) => channels.find((c: any) => c.id === id)?.name || id.slice(0, 6)).join(', ') : '-',
    },
    {
      title: '启用', dataIndex: 'enabled', key: 'enabled',
      render: (v: boolean, record: any) => <Switch size="small" checked={v} onChange={() => toggleRule(record)} />,
    },
    {
      title: '操作', key: 'action', width: 120,
      render: (_: any, record: any) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openRuleModal(record)} />
          <Popconfirm title="确定删除该规则？" onConfirm={() => deleteRule(record.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  // --- Notification Channels ---
  const openChannelModal = (channel?: any) => {
    setEditingChannel(channel || null)
    if (channel) {
      setChannelType(channel.type)
      const formValues: any = { name: channel.name, type: channel.type, enabled: channel.enabled }
      if (channel.type === 'email') {
        formValues.smtp_host = channel.config?.smtp_host
        formValues.smtp_port = channel.config?.smtp_port
        formValues.username = channel.config?.username
        formValues.recipients = (channel.config?.recipients || []).join(', ')
        formValues.use_ssl = channel.config?.use_ssl !== false
      } else {
        formValues.webhook_url = channel.config?.webhook_url
      }
      channelForm.setFieldsValue(formValues)
    } else {
      setChannelType('feishu')
      channelForm.resetFields()
      channelForm.setFieldsValue({ type: 'feishu', enabled: true })
    }
    setChannelModalOpen(true)
  }

  const saveChannel = async () => {
    const values = await channelForm.validateFields()
    let config: any = {}
    if (values.type === 'feishu' || values.type === 'wechat' || values.type === 'webhook') {
      config = { webhook_url: values.webhook_url }
    } else if (values.type === 'email') {
      config = {
        smtp_host: values.smtp_host,
        smtp_port: values.smtp_port || 465,
        username: values.username,
        password: values.password,
        use_ssl: values.use_ssl !== false,
        recipients: (values.recipients || '').split(',').map((s: string) => s.trim()).filter(Boolean),
      }
    }

    const payload = { name: values.name, type: values.type, config, enabled: values.enabled }

    if (editingChannel) {
      await client.put(`/notifications/channels/${editingChannel.id}`, payload)
      message.success('渠道已更新')
    } else {
      await client.post('/notifications/channels', payload)
      message.success('渠道已创建')
    }
    setChannelModalOpen(false)
    loadData()
  }

  const deleteChannel = async (id: string) => {
    await client.delete(`/notifications/channels/${id}`)
    message.success('渠道已删除')
    loadData()
  }

  const testChannel = async (id: string) => {
    try {
      const res = await client.post(`/notifications/channels/${id}/test`)
      if (res.data.success) {
        message.success('测试消息发送成功')
      } else {
        message.error('测试消息发送失败，请检查配置')
      }
    } catch {
      message.error('测试失败')
    }
  }

  const channelColumns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    {
      title: '类型', dataIndex: 'type', key: 'type',
      render: (t: string) => {
        const label = CHANNEL_TYPES.find(c => c.value === t)?.label || t
        return <Tag>{label}</Tag>
      },
    },
    {
      title: '配置', dataIndex: 'config', key: 'config',
      render: (config: any, record: any) => {
        if (record.type === 'feishu' || record.type === 'wechat' || record.type === 'webhook') {
          const url = config?.webhook_url || ''
          return url.length > 40 ? url.slice(0, 40) + '...' : url
        }
        if (record.type === 'email') {
          return `${config?.smtp_host || ''} → ${(config?.recipients || []).join(', ')}`
        }
        return '-'
      },
      ellipsis: true,
    },
    {
      title: '启用', dataIndex: 'enabled', key: 'enabled',
      render: (v: boolean) => <Badge status={v ? 'success' : 'default'} text={v ? '是' : '否'} />,
    },
    {
      title: '操作', key: 'action', width: 180,
      render: (_: any, record: any) => (
        <Space>
          <Button size="small" icon={<BellOutlined />} onClick={() => testChannel(record.id)}>测试</Button>
          <Button size="small" icon={<EditOutlined />} onClick={() => openChannelModal(record)} />
          <Popconfirm title="确定删除该渠道？" onConfirm={() => deleteChannel(record.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  // --- Condition form fields ---
  const renderConditionFields = () => {
    if (alertType === 'threshold') {
      return (
        <>
          <Form.Item name="operator" label="运算符" rules={[{ required: true, message: '请选择运算符' }]}>
            <Select options={OPERATOR_OPTIONS} />
          </Form.Item>
          <Form.Item name="threshold_value" label="阈值" rules={[{ required: true, message: '请输入阈值' }]}>
            <InputNumber style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="duration" label="持续时间 (秒)" tooltip="在该时间窗口内取均值判断">
            <InputNumber min={60} max={3600} style={{ width: '100%' }} />
          </Form.Item>
        </>
      )
    }
    if (alertType === 'anomaly') {
      return (
        <>
          <Form.Item name="z_threshold" label="Z-score 阈值" tooltip="超过该值视为异常">
            <InputNumber min={1} max={10} step={0.5} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="lookback_hours" label="回溯时间 (小时)">
            <InputNumber min={1} max={168} style={{ width: '100%' }} />
          </Form.Item>
        </>
      )
    }
    if (alertType === 'prediction') {
      return (
        <>
          <Form.Item name="predict_hours" label="预测时间 (小时)">
            <InputNumber min={1} max={168} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="capacity" label="容量阈值">
            <InputNumber min={1} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="lookback_days" label="训练数据天数">
            <InputNumber min={1} max={30} style={{ width: '100%' }} />
          </Form.Item>
        </>
      )
    }
    return null
  }

  // --- Channel config form fields ---
  const renderChannelConfigFields = () => {
    if (channelType === 'feishu' || channelType === 'wechat' || channelType === 'webhook') {
      const placeholder = channelType === 'feishu'
        ? 'https://open.feishu.cn/open-apis/bot/v2/hook/xxx'
        : channelType === 'wechat'
        ? 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx'
        : 'https://your-webhook-url.com/hook'
      return (
        <Form.Item name="webhook_url" label="Webhook URL" rules={[{ required: true, message: '请输入 Webhook URL' }]}>
          <Input placeholder={placeholder} />
        </Form.Item>
      )
    }
    if (channelType === 'email') {
      return (
        <>
          <Form.Item name="smtp_host" label="SMTP 服务器" rules={[{ required: true, message: '请输入 SMTP 服务器' }]}>
            <Input placeholder="smtp.example.com" />
          </Form.Item>
          <Form.Item name="smtp_port" label="端口">
            <InputNumber min={1} max={65535} placeholder="465" style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="username" label="用户名">
            <Input />
          </Form.Item>
          <Form.Item name="password" label="密码">
            <Input.Password />
          </Form.Item>
          <Form.Item name="recipients" label="收件人" rules={[{ required: true, message: '请输入收件人' }]} tooltip="多个邮箱以逗号分隔">
            <Input placeholder="a@example.com, b@example.com" />
          </Form.Item>
          <Form.Item name="use_ssl" label="SSL" valuePropName="checked" initialValue={true}>
            <Switch />
          </Form.Item>
        </>
      )
    }
    return null
  }

  return (
    <>
      <Tabs items={[
        {
          key: 'events',
          label: '告警事件',
          children: (
            <Table
              columns={eventColumns}
              dataSource={events}
              rowKey="id"
              pagination={{ pageSize: 20 }}
            />
          ),
        },
        {
          key: 'rules',
          label: '告警规则',
          children: (
            <>
              <div style={{ marginBottom: 16 }}>
                <Button type="primary" icon={<PlusOutlined />} onClick={() => openRuleModal()}>
                  新建规则
                </Button>
              </div>
              <Table columns={ruleColumns} dataSource={rules} rowKey="id" />
            </>
          ),
        },
        {
          key: 'channels',
          label: '通知渠道',
          children: (
            <>
              <div style={{ marginBottom: 16 }}>
                <Button type="primary" icon={<PlusOutlined />} onClick={() => openChannelModal()}>
                  新建渠道
                </Button>
              </div>
              <Table columns={channelColumns} dataSource={channels} rowKey="id" />
            </>
          ),
        },
      ]} />

      {/* Alert Rule Modal */}
      <Modal
        title={editingRule ? '编辑告警规则' : '新建告警规则'}
        open={ruleModalOpen}
        onOk={saveRule}
        onCancel={() => setRuleModalOpen(false)}
        width={600}
        destroyOnClose
      >
        <Form form={ruleForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="name" label="规则名称" rules={[{ required: true, message: '请输入规则名称' }]}>
            <Input placeholder="如：CPU 使用率过高告警" />
          </Form.Item>
          <Form.Item name="metric_name" label="监控指标" rules={[{ required: true, message: '请选择指标' }]}>
            <Select
              placeholder="选择指标"
              options={metricDefs.filter((m: any) => m.enabled).map((m: any) => ({ label: m.display_name, value: m.name }))}
            />
          </Form.Item>
          <Form.Item name="device_ids" label="关联设备" tooltip="留空表示对所有设备生效">
            <Select
              mode="multiple"
              placeholder="选择设备（可多选，留空=全部）"
              options={devices.map((d: any) => ({ label: d.name, value: d.id }))}
              allowClear
            />
          </Form.Item>
          <Form.Item name="type" label="告警类型" rules={[{ required: true }]}>
            <Select options={ALERT_TYPE_OPTIONS} onChange={(v) => setAlertType(v)} />
          </Form.Item>

          {renderConditionFields()}

          <Form.Item name="severity" label="告警级别">
            <Select options={SEVERITY_OPTIONS} />
          </Form.Item>
          <Form.Item name="notification_channel_ids" label="通知渠道">
            <Select
              mode="multiple"
              placeholder="选择通知渠道（可多选）"
              options={channels.map((c: any) => ({ label: `${c.name} (${CHANNEL_TYPES.find(t => t.value === c.type)?.label || c.type})`, value: c.id }))}
              allowClear
            />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      {/* Notification Channel Modal */}
      <Modal
        title={editingChannel ? '编辑通知渠道' : '新建通知渠道'}
        open={channelModalOpen}
        onOk={saveChannel}
        onCancel={() => setChannelModalOpen(false)}
        width={520}
        destroyOnClose
      >
        <Form form={channelForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="name" label="渠道名称" rules={[{ required: true, message: '请输入渠道名称' }]}>
            <Input placeholder="如：运维飞书群" />
          </Form.Item>
          <Form.Item name="type" label="渠道类型" rules={[{ required: true }]}>
            <Select options={CHANNEL_TYPES} onChange={(v) => setChannelType(v)} />
          </Form.Item>

          {renderChannelConfigFields()}

          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}

export default Alerts
