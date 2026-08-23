import { useState, useEffect, useCallback } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Layout, Menu, Dropdown, Tag, Modal, Form, Input, message, Space, Progress } from 'antd'
import {
  DashboardOutlined,
  CloudServerOutlined,
  LineChartOutlined,
  AlertOutlined,
  UploadOutlined,
  FileTextOutlined,
  SettingOutlined,
  UserOutlined,
  TeamOutlined,
  LogoutOutlined,
  KeyOutlined,
  DownOutlined,
  RobotOutlined,
} from '@ant-design/icons'
import client from '../api/client'

const { Header, Sider, Content } = Layout

const STRENGTH_COLORS = ['#ff4d4f', '#ff7a45', '#faad14', '#52c41a', '#52c41a']
const STRENGTH_LABELS = ['极弱', '弱', '一般', '强', '很强']

interface UserInfo {
  id: string
  username: string
  email: string
  role: string
}

const ROLE_COLORS: Record<string, string> = {
  admin: 'red',
  operator: 'blue',
  viewer: 'green',
}

const ROLE_LABELS: Record<string, string> = {
  admin: '管理员',
  operator: '操作员',
  viewer: '观察者',
}

const ALL_MENU_ITEMS = [
  { key: '/dashboard', icon: <DashboardOutlined />, label: '仪表盘', roles: ['admin', 'operator', 'viewer'] },
  { key: '/devices', icon: <CloudServerOutlined />, label: '设备管理', roles: ['admin', 'operator'] },
  { key: '/metrics', icon: <LineChartOutlined />, label: '指标数据', roles: ['admin', 'operator', 'viewer'] },
  { key: '/alerts', icon: <AlertOutlined />, label: '告警管理', roles: ['admin', 'operator'] },
  { key: '/upload', icon: <UploadOutlined />, label: 'ACC 数据', roles: ['admin', 'operator', 'viewer'] },
  { key: '/reports', icon: <FileTextOutlined />, label: '报表管理', roles: ['admin', 'operator'] },
  { key: '/copilot', icon: <RobotOutlined />, label: 'AI 助手', roles: ['admin', 'operator'] },
  { key: '/users', icon: <TeamOutlined />, label: '用户管理', roles: ['admin'] },
  { key: '/settings', icon: <SettingOutlined />, label: '系统设置', roles: ['admin'] },
]

function MainLayout() {
  const [collapsed, setCollapsed] = useState(false)
  const [userInfo, setUserInfo] = useState<UserInfo | null>(null)
  const [passwordModalOpen, setPasswordModalOpen] = useState(false)
  const [passwordForm] = Form.useForm()
  const [pwdStrength, setPwdStrength] = useState<{ score: number; errors: string[] } | null>(null)
  const [pwdCheckTimer, setPwdCheckTimer] = useState<ReturnType<typeof setTimeout> | null>(null)
  const navigate = useNavigate()
  const location = useLocation()

  const checkPasswordStrength = useCallback((password: string) => {
    if (pwdCheckTimer) clearTimeout(pwdCheckTimer)
    if (!password || password.length < 3) { setPwdStrength(null); return }
    const timer = setTimeout(async () => {
      try {
        const res = await client.post('/auth/password-check', {
          password,
          role: userInfo?.role || 'viewer',
          username: userInfo?.username || '',
        })
        setPwdStrength({ score: res.data.score, errors: res.data.errors })
      } catch { /* ignore */ }
    }, 300)
    setPwdCheckTimer(timer)
  }, [pwdCheckTimer, userInfo])

  useEffect(() => {
    client.get('/auth/me').then(res => {
      setUserInfo(res.data)
    }).catch(() => {
      navigate('/login')
    })
  }, [navigate])

  const handleLogout = () => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    navigate('/login')
  }

  const handleChangePassword = async (values: { old_password: string; new_password: string }) => {
    try {
      await client.put('/auth/password', values)
      message.success('密码已修改')
      setPasswordModalOpen(false)
      passwordForm.resetFields()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '修改失败')
    }
  }

  const menuItems = ALL_MENU_ITEMS.filter(item =>
    userInfo ? item.roles.includes(userInfo.role) : false
  )

  const dropdownItems = {
    items: [
      {
        key: 'password',
        icon: <KeyOutlined />,
        label: '修改密码',
        onClick: () => setPasswordModalOpen(true),
      },
      { type: 'divider' as const },
      {
        key: 'logout',
        icon: <LogoutOutlined />,
        label: '退出登录',
        danger: true,
        onClick: handleLogout,
      },
    ],
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed}>
        <div style={{ height: 32, margin: 16, color: '#fff', textAlign: 'center', fontSize: collapsed ? 16 : 14, fontWeight: 'bold', whiteSpace: 'nowrap', overflow: 'hidden' }}>
          {collapsed ? 'FW' : '防火墙集中监控系统'}
        </div>
        <Menu
          theme="dark"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Header style={{ padding: '0 24px', background: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'flex-end' }}>
          {userInfo && (
            <Dropdown menu={dropdownItems} trigger={['click']}>
              <Space style={{ cursor: 'pointer' }}>
                <UserOutlined />
                <span>{userInfo.username}</span>
                <Tag color={ROLE_COLORS[userInfo.role]}>{ROLE_LABELS[userInfo.role] || userInfo.role}</Tag>
                <DownOutlined style={{ fontSize: 10 }} />
              </Space>
            </Dropdown>
          )}
        </Header>
        <Content style={{ margin: 24, padding: 24, background: '#fff', borderRadius: 8 }}>
          <Outlet />
        </Content>
      </Layout>

      <Modal
        title="修改密码"
        open={passwordModalOpen}
        onCancel={() => { setPasswordModalOpen(false); passwordForm.resetFields(); setPwdStrength(null) }}
        onOk={() => passwordForm.submit()}
      >
        <Form form={passwordForm} onFinish={handleChangePassword} layout="vertical">
          <Form.Item name="old_password" label="当前密码" rules={[{ required: true, message: '请输入当前密码' }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item
            name="new_password"
            label="新密码"
            rules={[{ required: true, message: '请输入新密码' }]}
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
          >
            <Input.Password onChange={e => checkPasswordStrength(e.target.value)} />
          </Form.Item>
          <Form.Item
            name="confirm_password"
            label="确认新密码"
            dependencies={['new_password']}
            rules={[
              { required: true, message: '请确认新密码' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('new_password') === value) return Promise.resolve()
                  return Promise.reject(new Error('两次密码不一致'))
                },
              }),
            ]}
          >
            <Input.Password />
          </Form.Item>
        </Form>
      </Modal>
    </Layout>
  )
}

export default MainLayout
