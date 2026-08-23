import { useEffect, useState } from 'react'
import {
  Card, Descriptions, Tag, Table, Button, Modal, Form, Input, Select,
  Switch, InputNumber, Space, Popconfirm, message, Tooltip, Badge, Tabs,
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, QuestionCircleOutlined } from '@ant-design/icons'
import client from '../api/client'

const PARSER_TYPES_SSH = [
  { label: '正则(单值)', value: 'regex' },
  { label: '正则(多实例)', value: 'regex_multi' },
]

const PARSER_TYPES_API = [
  { label: 'XPath(单值)', value: 'xpath' },
  { label: 'XPath(多实例)', value: 'xpath_multi' },
  { label: '正则(CDATA)', value: 'regex_cdata' },
]

const DATA_TYPES = [
  { label: 'Gauge (瞬时值)', value: 'gauge' },
  { label: 'Counter (累计值)', value: 'counter' },
]

const CHART_TYPES = [
  { label: '折线图', value: 'line' },
  { label: '面积图', value: 'area' },
]

const CATEGORIES = [
  { label: '系统资源', value: 'system_resource' },
  { label: '硬件', value: 'hardware' },
  { label: '网络', value: 'network' },
  { label: 'HA', value: 'ha' },
  { label: '安全', value: 'security' },
  { label: '自定义', value: 'custom' },
]

function Settings() {
  const [health, setHealth] = useState<any>(null)
  const [sysSettings, setSysSettings] = useState<any>(null)
  const [collectors, setCollectors] = useState<string[]>([])
  const [metricDefs, setMetricDefs] = useState<any[]>([])
  const [aiForm] = Form.useForm()

  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<any>(null)
  const [form] = Form.useForm()
  const [selectedCollector, setSelectedCollector] = useState<string>('panos_ssh')
  const [selectedParserType, setSelectedParserType] = useState<string>('regex')

  const loadData = () => {
    client.get('/system/health').then(res => setHealth(res.data))
    client.get('/system/settings').then(res => setSysSettings(res.data))
    client.get('/system/collectors').then(res => setCollectors(res.data.collectors))
    client.get('/metrics/definitions').then(res => setMetricDefs(res.data.items))
    client.get('/system/ai-settings').then(res => {
      aiForm.setFieldsValue(res.data)
    }).catch(() => {})
  }

  const saveAiSettings = async () => {
    const values = await aiForm.validateFields()
    try {
      await client.put('/system/ai-settings', values)
      message.success('AI 配置已保存')
          } catch (e: any) {
      message.error(e.response?.data?.detail || '保存失败')
    }
  }

  useEffect(() => { loadData() }, [])

  const openModal = (metric?: any) => {
    setEditing(metric || null)
    if (metric) {
      setSelectedCollector(metric.collector)
      setSelectedParserType(metric.parser?.type || 'regex')
      form.setFieldsValue({
        name: metric.name,
        display_name: metric.display_name,
        category: metric.category,
        collector: metric.collector,
        command: metric.command,
        parser_type: metric.parser?.type,
        parser_pattern: metric.parser?.pattern,
        parser_expr: metric.parser?.expr,
        parser_entries_expr: metric.parser?.entries_expr,
        parser_value_expr: metric.parser?.value_expr,
        parser_label_expr: metric.parser?.label_expr,
        parser_calc: metric.parser?.calc,
        data_type: metric.data_type,
        unit: metric.unit,
        chart_type: metric.chart_type,
        interval: metric.interval,
        interval_min: metric.interval_min,
        interval_max: metric.interval_max,
        enabled: metric.enabled,
      })
    } else {
      setSelectedCollector('panos_ssh')
      setSelectedParserType('regex')
      form.resetFields()
      form.setFieldsValue({
        collector: 'panos_ssh',
        parser_type: 'regex',
        data_type: 'gauge',
        chart_type: 'line',
        category: 'custom',
        interval: 60,
        interval_min: 10,
        interval_max: 300,
        enabled: true,
      })
    }
    setModalOpen(true)
  }

  const saveMetric = async () => {
    const values = await form.validateFields()
    const parser: any = { type: values.parser_type }

    if (values.parser_type === 'regex' || values.parser_type === 'regex_multi' || values.parser_type === 'regex_cdata') {
      parser.pattern = values.parser_pattern
      if (values.parser_calc) parser.calc = values.parser_calc
    }
    if (values.parser_type === 'xpath') {
      parser.expr = values.parser_expr
    }
    if (values.parser_type === 'xpath_multi') {
      parser.entries_expr = values.parser_entries_expr
      parser.value_expr = values.parser_value_expr
      if (values.parser_label_expr) parser.label_expr = values.parser_label_expr
    }

    const payload = {
      name: values.name,
      display_name: values.display_name,
      category: values.category,
      collector: values.collector,
      command: values.command,
      parser,
      data_type: values.data_type,
      unit: values.unit || '',
      chart_type: values.chart_type,
      interval: values.interval,
      interval_min: values.interval_min,
      interval_max: values.interval_max,
      enabled: values.enabled,
    }

    try {
      if (editing) {
        await client.put(`/metrics/definitions/${editing.id}`, payload)
        message.success(editing.builtin ? '指标设置已更新' : '自定义指标已更新')
      } else {
        await client.post('/metrics/definitions', payload)
        message.success('自定义指标已创建，将在下一个采集周期自动开始采集')
      }
      setModalOpen(false)
      loadData()
    } catch (e: any) {
      message.error(e.response?.data?.detail || '操作失败')
    }
  }

  const deleteMetric = async (id: string) => {
    try {
      await client.delete(`/metrics/definitions/${id}`)
      message.success('指标已删除')
      loadData()
    } catch (e: any) {
      message.error(e.response?.data?.detail || '删除失败')
    }
  }

  const metricColumns = [
    { title: '指标名', dataIndex: 'name', key: 'name', width: 180 },
    { title: '显示名', dataIndex: 'display_name', key: 'display_name' },
    {
      title: '采集器', dataIndex: 'collector', key: 'collector',
      render: (v: string) => <Tag color={v === 'panos_ssh' ? 'green' : 'blue'}>{v}</Tag>,
    },
    {
      title: '分类', dataIndex: 'category', key: 'category',
      render: (v: string) => CATEGORIES.find(c => c.value === v)?.label || v,
    },
    { title: '间隔', dataIndex: 'interval', key: 'interval', render: (v: number) => `${v}s` },
    {
      title: '类型', dataIndex: 'builtin', key: 'builtin',
      render: (v: boolean) => v ? <Tag>内置</Tag> : <Tag color="purple">自定义</Tag>,
    },
    {
      title: '启用', dataIndex: 'enabled', key: 'enabled',
      render: (v: boolean) => <Badge status={v ? 'success' : 'default'} text={v ? '是' : '否'} />,
    },
    {
      title: '操作', key: 'action', width: 120,
      render: (_: any, record: any) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openModal(record)} />
          {!record.builtin && (
            <Popconfirm title="确定删除该指标定义？删除后历史数据仍保留。" onConfirm={() => deleteMetric(record.id)}>
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  const parserOptions = selectedCollector === 'panos_ssh' ? PARSER_TYPES_SSH : PARSER_TYPES_API

  const renderParserFields = () => {
    if (selectedParserType === 'regex' || selectedParserType === 'regex_multi' || selectedParserType === 'regex_cdata') {
      return (
        <>
          <Form.Item
            name="parser_pattern"
            label={
              <span>
                正则表达式&nbsp;
                <Tooltip title="regex: 第一个捕获组为数值。regex_multi: 第一组为实例名、第二组为数值。regex_cdata: 在 XML 文本内容中匹配。">
                  <QuestionCircleOutlined />
                </Tooltip>
              </span>
            }
            rules={[{ required: true, message: '请输入正则表达式' }]}
          >
            <Input.TextArea rows={2} placeholder='如: (?m)^\s*(\S+)\s+.+?\s+([\d.]+)' />
          </Form.Item>
          {(selectedParserType === 'regex_cdata') && (
            <Form.Item name="parser_calc" label="计算公式" tooltip="支持: value1 / value0 * 100 等">
              <Input placeholder="可选，如 value1 / value0 * 100" />
            </Form.Item>
          )}
        </>
      )
    }
    if (selectedParserType === 'xpath') {
      return (
        <Form.Item name="parser_expr" label="XPath 表达式" rules={[{ required: true, message: '请输入 XPath' }]}>
          <Input placeholder="如: .//num-active" />
        </Form.Item>
      )
    }
    if (selectedParserType === 'xpath_multi') {
      return (
        <>
          <Form.Item name="parser_entries_expr" label="条目 XPath" rules={[{ required: true }]} tooltip="定位多个条目的 XPath">
            <Input placeholder="如: .//ifnet/ifnet/entry" />
          </Form.Item>
          <Form.Item name="parser_value_expr" label="值 XPath" rules={[{ required: true }]} tooltip="从每个条目中取值的 XPath">
            <Input placeholder="如: ibytes/text()" />
          </Form.Item>
          <Form.Item name="parser_label_expr" label="标签 XPath" tooltip="标识实例名称，默认 @name">
            <Input placeholder="如: name/text()" />
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
          key: 'overview',
          label: '系统概览',
          children: (
            <div>
              <Card title="系统状态" style={{ marginBottom: 16 }}>
                {health && (
                  <Descriptions>
                    <Descriptions.Item label="整体状态">
                      <Tag color={health.status === 'ok' ? 'green' : 'orange'}>{health.status}</Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label="数据库">
                      <Tag color={health.database ? 'green' : 'red'}>{health.database ? '正常' : '异常'}</Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label="Redis">
                      <Tag color={health.redis ? 'green' : 'red'}>{health.redis ? '正常' : '异常'}</Tag>
                    </Descriptions.Item>
                  </Descriptions>
                )}
              </Card>

              <Card title="系统配置" style={{ marginBottom: 16 }}>
                {sysSettings && (
                  <Descriptions column={2}>
                    <Descriptions.Item label="数据保留天数">{sysSettings.retention_raw_days} 天</Descriptions.Item>
                    <Descriptions.Item label="压缩起始天数">{sysSettings.compress_after_days} 天</Descriptions.Item>
                    <Descriptions.Item label="采集并发数">{sysSettings.collector_concurrency}</Descriptions.Item>
                    <Descriptions.Item label="采集超时">{sysSettings.collector_timeout} 秒</Descriptions.Item>
                  </Descriptions>
                )}
              </Card>

              <Card title="可用采集器">
                <Space>
                  {collectors.map(c => (
                    <Tag key={c} color={c === 'panos_ssh' ? 'green' : c === 'panos_api' ? 'blue' : 'default'}>
                      {c}
                    </Tag>
                  ))}
                </Space>
                <div style={{ marginTop: 12, color: '#888', fontSize: 13 }}>
                  采集器是数据采集的执行引擎。<strong>panos_api</strong> 通过 XML API 采集（适合结构化数据），<strong>panos_ssh</strong> 通过 SSH CLI 采集（适合文本输出解析）。
                  在「指标管理」Tab 中可为任意采集器自定义采集命令和解析规则。
                </div>
              </Card>
            </div>
          ),
        },
        {
          key: 'ai',
          label: 'AI 助手',
          children: (
            <Card title="AI 模型配置" extra={<Button type="primary" onClick={saveAiSettings}>保存</Button>}>
              <Form form={aiForm} layout="vertical" style={{ maxWidth: 500 }}>
                <Form.Item name="api_base" label="API Base URL" tooltip="兼容 OpenAI 格式的 API 地址">
                  <Input placeholder="如: https://api.deepseek.com/v1" />
                </Form.Item>
                <Form.Item name="api_key" label="API Key">
                  <Input.Password placeholder="sk-..." />
                </Form.Item>
                <Form.Item name="model" label="模型名称">
                  <Input placeholder="如: deepseek-chat, gpt-4o-mini" />
                </Form.Item>
              </Form>
              <div style={{ color: '#888', fontSize: 13, marginTop: 8 }}>
                配置后可在「AI 助手」页面使用自然语言查询设备状态、威胁排名等信息。
                支持任何兼容 OpenAI Chat Completions API 格式的服务（DeepSeek、OpenAI、Ollama 等）。
              </div>
            </Card>
          ),
        },
        {
          key: 'metrics',
          label: '指标管理',
          children: (
            <>
              <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ color: '#888' }}>
                  管理指标定义。自定义指标创建后将自动按设定间隔采集，数据在「指标数据」页面可视化展示。
                </span>
                <Button type="primary" icon={<PlusOutlined />} onClick={() => openModal()}>
                  新建自定义指标
                </Button>
              </div>
              <Table
                columns={metricColumns}
                dataSource={metricDefs}
                rowKey="id"
                pagination={false}
                size="middle"
              />
            </>
          ),
        },
      ]} />

      <Modal
        title={editing ? (editing.builtin ? '编辑内置指标（仅可调整间隔）' : '编辑自定义指标') : '新建自定义指标'}
        open={modalOpen}
        onOk={saveMetric}
        onCancel={() => setModalOpen(false)}
        width={680}
        destroyOnClose
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="name" label="指标标识名" rules={[{ required: true, message: '请输入英文标识名' }]} tooltip="唯一英文标识，如 vpn_tunnel_count">
            <Input placeholder="如: vpn_tunnel_count" disabled={!!editing} />
          </Form.Item>
          <Form.Item name="display_name" label="显示名称" rules={[{ required: true, message: '请输入显示名称' }]}>
            <Input placeholder="如: VPN 隧道数量" disabled={editing?.builtin} />
          </Form.Item>

          <Space style={{ width: '100%' }} size="middle">
            <Form.Item name="category" label="分类" style={{ width: 180 }}>
              <Select options={CATEGORIES} disabled={editing?.builtin} />
            </Form.Item>
            <Form.Item name="collector" label="采集器" style={{ width: 180 }} rules={[{ required: true }]}>
              <Select
                options={collectors.map(c => ({ label: c, value: c }))}
                disabled={editing?.builtin}
                onChange={(v) => {
                  setSelectedCollector(v)
                  const defaultType = v === 'panos_ssh' ? 'regex' : 'xpath'
                  setSelectedParserType(defaultType)
                  form.setFieldValue('parser_type', defaultType)
                }}
              />
            </Form.Item>
          </Space>

          <Form.Item
            name="command"
            label={selectedCollector === 'panos_ssh' ? 'SSH CLI 命令' : 'XML API 命令'}
            rules={[{ required: true, message: '请输入采集命令' }]}
            tooltip={selectedCollector === 'panos_ssh'
              ? '直接输入 PAN-OS CLI 命令，如: show vpn ipsec-sa'
              : '输入 XML 格式 op command，如: <show><vpn><ipsec-sa></ipsec-sa></vpn></show>'
            }
          >
            <Input.TextArea
              rows={2}
              placeholder={selectedCollector === 'panos_ssh'
                ? 'show vpn ipsec-sa'
                : '<show><vpn><ipsec-sa></ipsec-sa></vpn></show>'
              }
              disabled={editing?.builtin}
            />
          </Form.Item>

          <Form.Item name="parser_type" label="解析方式" rules={[{ required: true }]}>
            <Select
              options={parserOptions}
              disabled={editing?.builtin}
              onChange={(v) => setSelectedParserType(v)}
            />
          </Form.Item>

          {!editing?.builtin && renderParserFields()}

          <Space style={{ width: '100%' }} size="middle">
            <Form.Item name="data_type" label="数据类型" style={{ width: 180 }}>
              <Select options={DATA_TYPES} disabled={editing?.builtin} />
            </Form.Item>
            <Form.Item name="unit" label="单位" style={{ width: 120 }}>
              <Input placeholder="如: %, °C, bytes" disabled={editing?.builtin} />
            </Form.Item>
            <Form.Item name="chart_type" label="图表类型" style={{ width: 140 }}>
              <Select options={CHART_TYPES} disabled={editing?.builtin} />
            </Form.Item>
          </Space>

          <Space style={{ width: '100%' }} size="middle">
            <Form.Item name="interval" label="采集间隔(秒)" rules={[{ required: true }]}>
              <InputNumber min={10} max={86400} style={{ width: 130 }} />
            </Form.Item>
            <Form.Item name="interval_min" label="最小间隔" style={{ width: 130 }}>
              <InputNumber min={5} disabled={editing?.builtin} />
            </Form.Item>
            <Form.Item name="interval_max" label="最大间隔" style={{ width: 130 }}>
              <InputNumber min={60} disabled={editing?.builtin} />
            </Form.Item>
          </Space>

          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}

export default Settings
