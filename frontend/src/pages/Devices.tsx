import { useEffect, useState } from 'react'
import { Table, Button, Modal, Form, Input, Select, Space, Tag, Tabs, message, Result, Spin, Descriptions, Popconfirm } from 'antd'
import { PlusOutlined, CheckCircleOutlined, CloseCircleOutlined, LoadingOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import client from '../api/client'

interface GroupOption {
  id: string
  name: string
}

interface GroupRecord {
  id: string
  name: string
  description: string | null
  device_count: number
  created_at: string
}

function DeviceGroupsTab({ onGroupsChange }: { onGroupsChange: () => void }) {
  const [groups, setGroups] = useState<GroupRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<GroupRecord | null>(null)
  const [form] = Form.useForm()

  const fetchGroups = async () => {
    setLoading(true)
    try {
      const res = await client.get('/device-groups')
      setGroups(res.data.items)
    } catch {
      message.error('获取分组列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchGroups() }, [])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    setModalOpen(true)
  }

  const openEdit = (record: GroupRecord) => {
    setEditing(record)
    form.setFieldsValue({ name: record.name, description: record.description })
    setModalOpen(true)
  }

  const handleSubmit = async (values: any) => {
    try {
      if (editing) {
        await client.put(`/device-groups/${editing.id}`, values)
        message.success('分组已更新')
      } else {
        await client.post('/device-groups', values)
        message.success('分组已创建')
      }
      setModalOpen(false)
      fetchGroups()
      onGroupsChange()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '操作失败')
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await client.delete(`/device-groups/${id}`)
      message.success('分组已删除')
      fetchGroups()
      onGroupsChange()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '删除失败')
    }
  }

  const columns = [
    { title: '分组名称', dataIndex: 'name', key: 'name' },
    { title: '描述', dataIndex: 'description', key: 'description', render: (v: string | null) => v || '-' },
    { title: '设备数量', dataIndex: 'device_count', key: 'device_count' },
    {
      title: '创建时间', dataIndex: 'created_at', key: 'created_at',
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作', key: 'actions',
      render: (_: any, record: GroupRecord) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)}>编辑</Button>
          <Popconfirm title="删除后，分组内设备将变为未分组。确定删除？" onConfirm={() => handleDelete(record.id)}>
            <Button size="small" icon={<DeleteOutlined />} danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建分组</Button>
      </div>
      <Table dataSource={groups} columns={columns} rowKey="id" loading={loading} pagination={false} />
      <Modal
        title={editing ? '编辑分组' : '新建分组'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
        destroyOnClose
      >
        <Form form={form} onFinish={handleSubmit} layout="vertical">
          <Form.Item name="name" label="分组名称" rules={[{ required: true, message: '请输入分组名称' }]}>
            <Input placeholder="如：北京机房、海外节点" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} placeholder="可选描述" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

function Devices() {
  const [devices, setDevices] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [form] = Form.useForm()
  const [groups, setGroups] = useState<GroupOption[]>([])
  const [filterGroupId, setFilterGroupId] = useState<string | undefined>(undefined)

  const fetchGroups = async () => {
    try {
      const res = await client.get('/device-groups')
      setGroups(res.data.items)
    } catch { /* ignore */ }
  }

  const fetchDevices = (groupId?: string) => {
    setLoading(true)
    const params: any = {}
    if (groupId) params.group_id = groupId
    client.get('/devices', { params }).then(res => {
      setDevices(res.data.items)
    }).finally(() => setLoading(false))
  }

  useEffect(() => {
    fetchGroups()
    fetchDevices()
  }, [])

  const handleFilterChange = (value: string) => {
    setFilterGroupId(value || undefined)
    fetchDevices(value || undefined)
  }

  const handleCreate = async () => {
    const values = await form.validateFields()
    await client.post('/devices', values)
    message.success('设备添加成功')
    setModalOpen(false)
    form.resetFields()
    fetchDevices(filterGroupId)
  }

  const handleChangeGroup = async (deviceId: string, groupId: string | null) => {
    try {
      await client.put(`/devices/${deviceId}`, { group_id: groupId })
      fetchDevices(filterGroupId)
    } catch {
      message.error('分组修改失败')
    }
  }

  const columns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '地址', dataIndex: 'hostname', key: 'hostname' },
    { title: '型号', dataIndex: 'model', key: 'model' },
    { title: '序列号', dataIndex: 'serial', key: 'serial' },
    { title: 'PAN-OS', dataIndex: 'panos_version', key: 'panos_version' },
    {
      title: '分组', key: 'group',
      render: (_: any, record: any) => (
        <Select
          value={record.group_id || undefined}
          placeholder="未分组"
          allowClear
          size="small"
          style={{ width: 120 }}
          onChange={(val) => handleChangeGroup(record.id, val || null)}
          options={groups.map(g => ({ value: g.id, label: g.name }))}
        />
      ),
    },
    {
      title: '状态', dataIndex: 'status', key: 'status',
      render: (s: string) => <Tag color={s === 'online' ? 'green' : 'red'}>{s}</Tag>,
    },
    { title: 'HA', dataIndex: 'ha_state', key: 'ha_state' },
    {
      title: '操作', key: 'action',
      render: (_: any, record: any) => (
        <Space>
          <Button size="small" onClick={() => testConnection(record.id)}>测试连接</Button>
          <Button size="small" danger onClick={() => deleteDevice(record.id)}>删除</Button>
        </Space>
      ),
    },
  ]

  const [testModalOpen, setTestModalOpen] = useState(false)
  const [testLoading, setTestLoading] = useState(false)
  const [testResults, setTestResults] = useState<{ api?: boolean; ssh?: boolean } | null>(null)
  const [testDeviceName, setTestDeviceName] = useState('')

  const testConnection = async (id: string) => {
    const device = devices.find(d => d.id === id)
    setTestDeviceName(device?.name || id)
    setTestResults(null)
    setTestLoading(true)
    setTestModalOpen(true)
    try {
      const res = await client.post(`/devices/${id}/test-connection`)
      setTestResults(res.data.results)
    } catch {
      setTestResults({ api: false, ssh: false })
    } finally {
      setTestLoading(false)
    }
  }

  const deleteDevice = async (id: string) => {
    Modal.confirm({
      title: '确认删除?',
      onOk: async () => {
        await client.delete(`/devices/${id}`)
        message.success('已删除')
        fetchDevices(filterGroupId)
      },
    })
  }

  return (
    <div>
      <h2 style={{ margin: '0 0 16px 0' }}>设备管理</h2>
      <Tabs
        defaultActiveKey="devices"
        items={[
          {
            key: 'devices',
            label: '设备列表',
            children: (
              <>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
                  <Select
                    placeholder="筛选分组"
                    allowClear
                    style={{ width: 160 }}
                    value={filterGroupId}
                    onChange={handleFilterChange}
                    options={[
                      { value: 'ungrouped', label: '未分组' },
                      ...groups.map(g => ({ value: g.id, label: g.name })),
                    ]}
                  />
                  <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
                    添加设备
                  </Button>
                </div>
                <Table columns={columns} dataSource={devices} rowKey="id" loading={loading} />
              </>
            ),
          },
          {
            key: 'groups',
            label: '分组管理',
            children: <DeviceGroupsTab onGroupsChange={fetchGroups} />,
          },
        ]}
      />

      <Modal title="添加设备" open={modalOpen} onOk={handleCreate} onCancel={() => setModalOpen(false)}>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="设备名称" rules={[{ required: true }]}>
            <Input placeholder="PA-5450-01" />
          </Form.Item>
          <Form.Item name="hostname" label="IP/主机名" rules={[{ required: true }]}>
            <Input placeholder="10.1.1.1" />
          </Form.Item>
          <Form.Item name="ssh_username" label="SSH 用户名" rules={[{ required: true }]}>
            <Input placeholder="admin" />
          </Form.Item>
          <Form.Item name="ssh_password" label="SSH 密码" rules={[{ required: true }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item name="group_id" label="分组">
            <Select
              placeholder="可选，选择设备分组"
              allowClear
              options={groups.map(g => ({ value: g.id, label: g.name }))}
            />
          </Form.Item>
        </Form>
        <p style={{ color: '#888', fontSize: 12 }}>API Key 将通过设备凭据自动获取</p>
      </Modal>

      <Modal
        title={`连接测试 - ${testDeviceName}`}
        open={testModalOpen}
        onCancel={() => setTestModalOpen(false)}
        footer={<Button onClick={() => setTestModalOpen(false)}>关闭</Button>}
      >
        {testLoading ? (
          <div style={{ textAlign: 'center', padding: '40px 0' }}>
            <Spin indicator={<LoadingOutlined style={{ fontSize: 36 }} />} />
            <p style={{ marginTop: 16, color: '#888' }}>正在测试连接...</p>
          </div>
        ) : testResults ? (
          <div>
            {Object.values(testResults).every(v => v) ? (
              <Result status="success" title="所有连接正常" />
            ) : Object.values(testResults).every(v => !v) ? (
              <Result status="error" title="连接失败" subTitle="请检查设备地址和凭据" />
            ) : (
              <Result status="warning" title="部分连接异常" />
            )}
            <Descriptions column={1} bordered size="small">
              {'api' in testResults && (
                <Descriptions.Item label="API (HTTPS)">
                  {testResults.api
                    ? <Tag icon={<CheckCircleOutlined />} color="success">正常</Tag>
                    : <Tag icon={<CloseCircleOutlined />} color="error">失败</Tag>}
                </Descriptions.Item>
              )}
              {'ssh' in testResults && (
                <Descriptions.Item label="SSH">
                  {testResults.ssh
                    ? <Tag icon={<CheckCircleOutlined />} color="success">正常</Tag>
                    : <Tag icon={<CloseCircleOutlined />} color="error">失败</Tag>}
                </Descriptions.Item>
              )}
            </Descriptions>
          </div>
        ) : null}
      </Modal>
    </div>
  )
}

export default Devices
