import { useState, useEffect, useCallback } from 'react'
import { Table, Button, Modal, Form, Input, Select, Switch, Space, Tag, message, Popconfirm, Tooltip, Progress } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, InfoCircleOutlined } from '@ant-design/icons'
import client from '../api/client'

interface UserRecord {
  id: string
  username: string
  email: string
  role: string
  is_active: boolean
  created_at: string
  group_ids: string[]
  group_names: string[]
}

interface GroupOption {
  id: string
  name: string
}

const ROLE_OPTIONS = [
  { value: 'admin', label: '管理员' },
  { value: 'operator', label: '操作员' },
  { value: 'viewer', label: '观察者' },
]

const ROLE_COLORS: Record<string, string> = {
  admin: 'red',
  operator: 'blue',
  viewer: 'green',
}

const STRENGTH_COLORS = ['#ff4d4f', '#ff7a45', '#faad14', '#52c41a', '#52c41a']
const STRENGTH_LABELS = ['极弱', '弱', '一般', '强', '很强']

function Users() {
  const [users, setUsers] = useState<UserRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<UserRecord | null>(null)
  const [form] = Form.useForm()
  const [groups, setGroups] = useState<GroupOption[]>([])
  const [pwdStrength, setPwdStrength] = useState<{ score: number; errors: string[] } | null>(null)
  const [pwdCheckTimer, setPwdCheckTimer] = useState<ReturnType<typeof setTimeout> | null>(null)

  const checkPasswordStrength = useCallback((password: string, role: string, username: string) => {
    if (pwdCheckTimer) clearTimeout(pwdCheckTimer)
    if (!password || password.length < 3) {
      setPwdStrength(null)
      return
    }
    const timer = setTimeout(async () => {
      try {
        const res = await client.post('/auth/password-check', { password, role, username })
        setPwdStrength({ score: res.data.score, errors: res.data.errors })
      } catch { /* ignore */ }
    }, 300)
    setPwdCheckTimer(timer)
  }, [pwdCheckTimer])

  const fetchUsers = async () => {
    setLoading(true)
    try {
      const res = await client.get('/users')
      setUsers(res.data.items)
    } catch {
      message.error('获取用户列表失败')
    } finally {
      setLoading(false)
    }
  }

  const fetchGroups = async () => {
    try {
      const res = await client.get('/device-groups')
      setGroups(res.data.items)
    } catch { /* ignore */ }
  }

  useEffect(() => { fetchUsers(); fetchGroups() }, [])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    setPwdStrength(null)
    setModalOpen(true)
  }

  const openEdit = (record: UserRecord) => {
    setEditing(record)
    setPwdStrength(null)
    form.setFieldsValue({
      username: record.username,
      email: record.email,
      role: record.role,
      group_ids: record.group_ids,
    })
    setModalOpen(true)
  }

  const handleSubmit = async (values: any) => {
    try {
      if (editing) {
        const payload: any = {
          username: values.username,
          email: values.email,
          role: values.role,
          group_ids: values.group_ids || [],
        }
        if (values.password) payload.password = values.password
        await client.put(`/users/${editing.id}`, payload)
        message.success('用户已更新')
      } else {
        await client.post('/users', { ...values, group_ids: values.group_ids || [] })
        message.success('用户已创建')
      }
      setModalOpen(false)
      fetchUsers()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '操作失败')
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await client.delete(`/users/${id}`)
      message.success('用户已删除')
      fetchUsers()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '删除失败')
    }
  }

  const handleToggleActive = async (record: UserRecord) => {
    try {
      await client.put(`/users/${record.id}`, { is_active: !record.is_active })
      fetchUsers()
    } catch {
      message.error('操作失败')
    }
  }

  const columns = [
    { title: '用户名', dataIndex: 'username', key: 'username' },
    { title: '邮箱', dataIndex: 'email', key: 'email' },
    {
      title: '角色', dataIndex: 'role', key: 'role',
      render: (role: string) => <Tag color={ROLE_COLORS[role]}>{ROLE_OPTIONS.find(r => r.value === role)?.label || role}</Tag>,
    },
    {
      title: '可访问分组', key: 'groups',
      render: (_: any, record: UserRecord) => (
        record.group_names.length > 0
          ? record.group_names.map((name, i) => <Tag key={i}>{name}</Tag>)
          : <Tag color="default">全局访问</Tag>
      ),
    },
    {
      title: '状态', dataIndex: 'is_active', key: 'is_active',
      render: (active: boolean, record: UserRecord) => (
        <Switch checked={active} onChange={() => handleToggleActive(record)} checkedChildren="启用" unCheckedChildren="禁用" />
      ),
    },
    {
      title: '操作', key: 'actions',
      render: (_: any, record: UserRecord) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)}>编辑</Button>
          <Popconfirm title="确定删除该用户？" onConfirm={() => handleDelete(record.id)}>
            <Button size="small" icon={<DeleteOutlined />} danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>用户管理</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建用户</Button>
      </div>

      <Table dataSource={users} columns={columns} rowKey="id" loading={loading} />

      <Modal
        title={editing ? '编辑用户' : '新建用户'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
        destroyOnClose
      >
        <Form form={form} onFinish={handleSubmit} layout="vertical">
          <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="email" label="邮箱" rules={[{ required: true, type: 'email', message: '请输入有效邮箱' }]}>
            <Input />
          </Form.Item>
          <Form.Item
            name="password"
            label={editing ? '新密码（留空不修改）' : '密码'}
            rules={editing ? [] : [{ required: true, message: '请输入密码' }]}
            help={
              pwdStrength && (
                <div style={{ marginTop: 4 }}>
                  <Space size={8} align="center">
                    <Progress
                      percent={(pwdStrength.score + 1) * 25}
                      steps={4}
                      size="small"
                      strokeColor={STRENGTH_COLORS[pwdStrength.score]}
                      showInfo={false}
                      style={{ width: 100 }}
                    />
                    <span style={{ color: STRENGTH_COLORS[pwdStrength.score], fontSize: 12 }}>
                      {STRENGTH_LABELS[pwdStrength.score]}
                    </span>
                  </Space>
                  {pwdStrength.errors.length > 0 && (
                    <div style={{ color: '#ff4d4f', fontSize: 12, marginTop: 2 }}>
                      {pwdStrength.errors[0]}
                    </div>
                  )}
                </div>
              )
            }
            extra={!pwdStrength && !editing && <span style={{ fontSize: 12, color: '#999' }}>至少8位，须含大小写字母、数字和特殊字符</span>}
          >
            <Input.Password
              onChange={e => {
                const role = form.getFieldValue('role') || 'viewer'
                const username = form.getFieldValue('username') || ''
                checkPasswordStrength(e.target.value, role, username)
              }}
            />
          </Form.Item>
          <Form.Item name="role" label="角色" rules={[{ required: true, message: '请选择角色' }]} initialValue="viewer">
            <Select options={ROLE_OPTIONS} />
          </Form.Item>
          <Form.Item
            name="group_ids"
            label={
              <Space>
                可访问分组
                <Tooltip title="不选择任何分组表示全局访问（可看到所有设备）">
                  <InfoCircleOutlined style={{ color: '#999' }} />
                </Tooltip>
              </Space>
            }
          >
            <Select
              mode="multiple"
              placeholder="不选 = 全局访问（所有设备）"
              allowClear
              options={groups.map(g => ({ value: g.id, label: g.name }))}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default Users
