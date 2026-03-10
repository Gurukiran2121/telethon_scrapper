import React, { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Col,
  Form,
  Input,
  Layout,
  List,
  Row,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";

const { Header, Content } = Layout;
const { Title, Text } = Typography;

const API_BASE = import.meta.env.VITE_API_BASE || "";

const fetchJson = async (path, options) => {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const text = await res.text();
  if (text?.trim().startsWith("<!doctype")) {
    throw new Error(
      "API returned HTML. Check VITE_API_BASE or the Vite proxy.",
    );
  }
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const detail = data?.detail || res.statusText;
    throw new Error(detail);
  }
  return data;
};

export default function App() {
  const [error, setError] = useState("");
  const [authStatus, setAuthStatus] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [phoneNumber, setPhoneNumber] = useState("");
  const [isAuthorized, setIsAuthorized] = useState(false);
  const [sendingOtp, setSendingOtp] = useState(false);
  const [verifyingOtp, setVerifyingOtp] = useState(false);
  const [checkingStatus, setCheckingStatus] = useState(true);
  const [loggingOut, setLoggingOut] = useState(false);

  const [availableChats, setAvailableChats] = useState([]);
  const [enabledChats, setEnabledChats] = useState([]);
  const [activeJobs, setActiveJobs] = useState([]);

  const loadAvailableChats = async () => {
    const data = await fetchJson("/available-chats?limit=300");
    setAvailableChats(Array.isArray(data) ? data : []);
  };

  const loadEnabledChats = async () => {
    const data = await fetchJson("/enabled-chats");
    setEnabledChats(Array.isArray(data) ? data : []);
  };

  const loadActiveJobs = async () => {
    const data = await fetchJson("/active-jobs");
    setActiveJobs(Array.isArray(data) ? data : []);
  };

  const refreshDashboard = async () => {
    try {
      setError("");
      await Promise.all([
        loadAvailableChats(),
        loadEnabledChats(),
        loadActiveJobs(),
      ]);
    } catch (err) {
      setError(err.message || "Failed to load dashboard data");
    }
  };

  useEffect(() => {
    const checkStatus = async () => {
      setCheckingStatus(true);
      try {
        const status = await fetchJson("/auth/status");
        if (status?.authorized) {
          setIsAuthorized(true);
          await refreshDashboard();
        }
      } catch (err) {
        setError(err.message || "Failed to check auth status");
      } finally {
        setCheckingStatus(false);
      }
    };

    checkStatus();
  }, []);

  useEffect(() => {
    if (!isAuthorized) return;
    const interval = setInterval(() => {
      loadActiveJobs();
    }, 3000);
    return () => clearInterval(interval);
  }, [isAuthorized]);

  const onAuthStart = async (values) => {
    setError("");
    setAuthStatus("");
    setSendingOtp(true);
    try {
      const payload = {
        api_id: Number(values.api_id),
        api_hash: values.api_hash,
        phone_number: values.phone_number,
        session_name: values.session_name || undefined,
      };
      await fetchJson("/auth/start", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setAuthStatus("OTP sent. Enter the code to verify.");
      setOtpSent(true);
      setPhoneNumber(values.phone_number);
    } catch (err) {
      setError(err.message || "Failed to send OTP");
    } finally {
      setSendingOtp(false);
    }
  };

  const onAuthVerify = async (values) => {
    setError("");
    setAuthStatus("");
    setVerifyingOtp(true);
    try {
      if (!phoneNumber) {
        throw new Error("Phone number is missing. Send OTP first.");
      }
      const payload = {
        phone_number: phoneNumber,
        otp: values.otp,
        password: values.password || undefined,
      };
      await fetchJson("/auth/verify", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setAuthStatus("Authorized. Scraper will start shortly.");
      setOtpSent(false);
      setIsAuthorized(true);
      await refreshDashboard();
    } catch (err) {
      setError(err.message || "Failed to verify OTP");
    } finally {
      setVerifyingOtp(false);
    }
  };

  const onLogout = async () => {
    setError("");
    setAuthStatus("");
    setLoggingOut(true);
    try {
      await fetchJson("/auth/logout", { method: "POST" });
      setIsAuthorized(false);
      setOtpSent(false);
      setPhoneNumber("");
      setAvailableChats([]);
      setEnabledChats([]);
      setActiveJobs([]);
      setAuthStatus("Logged out.");
    } catch (err) {
      setError(err.message || "Failed to log out");
    } finally {
      setLoggingOut(false);
    }
  };

  const onAddChat = async (values) => {
    setError("");
    if (!values.chat_identifier?.trim()) return;
    try {
      await fetchJson(
        `/chats?chat_identifier=${encodeURIComponent(values.chat_identifier)}`,
        { method: "POST" },
      );
      await loadEnabledChats();
    } catch (err) {
      setError(err.message || "Failed to add chat");
    }
  };

  const availableChatColumns = [
    {
      title: "Name",
      key: "name",
      render: (_, row) => row.title || row.username || row.id,
    },
    {
      title: "Username",
      dataIndex: "username",
      key: "username",
      render: (value) => value || "-",
    },
    {
      title: "Type",
      dataIndex: "type",
      key: "type",
      render: (value) => <Tag>{String(value).toUpperCase()}</Tag>,
    },
  ];

  const jobColumns = [
    { title: "File", dataIndex: "filename", key: "filename" },
    { title: "Chat", dataIndex: "chat_name", key: "chat_name" },
    {
      title: "Progress",
      key: "progress",
      render: (_, job) => `${job.progress_percent || 0}%`,
    },
    {
      title: "Speed",
      dataIndex: "speed_mb_s",
      key: "speed_mb_s",
      render: (value) => `${value || 0} MB/s`,
    },
  ];

  const dashboardVisible = isAuthorized;

  return (
    <Layout className="app-layout">
      <Header className="app-header">
        <Title level={3} style={{ margin: 0 }}>
          Telegram Scrapper
        </Title>
        <Space>
          {dashboardVisible ? (
            <Button onClick={refreshDashboard}>Refresh</Button>
          ) : null}
          {dashboardVisible ? (
            <Button danger onClick={onLogout} loading={loggingOut}>
              Logout
            </Button>
          ) : null}
        </Space>
      </Header>
      <Content className="app-content">
        <div className="auth-wrap">
          <Space direction="vertical" style={{ width: "100%" }} size="middle">
            {error ? <Alert message={error} type="error" showIcon /> : null}
            {authStatus ? (
              <Alert message={authStatus} type="success" showIcon />
            ) : null}
          </Space>

          <Card title="Telegram Authentication" loading={checkingStatus}>
            {dashboardVisible ? (
              <Text type="secondary">
                Session is active. Use Logout to switch accounts.
              </Text>
            ) : (
              <>
                <Form layout="vertical" onFinish={onAuthStart}>
                  <Row gutter={[16, 16]}>
                    <Col xs={24} md={12} lg={6}>
                      <Form.Item
                        label="API ID"
                        name="api_id"
                        rules={[
                          { required: true, message: "API ID is required" },
                        ]}
                      >
                        <Input placeholder="123456" />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={12} lg={6}>
                      <Form.Item
                        label="API Hash"
                        name="api_hash"
                        rules={[
                          { required: true, message: "API Hash is required" },
                        ]}
                      >
                        <Input placeholder="abcdef123..." />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={12} lg={6}>
                      <Form.Item label="Session Name" name="session_name">
                        <Input placeholder="telethon_15551234567" />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={12} lg={6}>
                      <Form.Item
                        label="Phone Number"
                        name="phone_number"
                        rules={[
                          {
                            required: true,
                            message: "Phone number is required",
                          },
                        ]}
                      >
                        <Input placeholder="+15551234567" />
                      </Form.Item>
                    </Col>
                  </Row>
                  <Button type="primary" htmlType="submit" loading={sendingOtp}>
                    Send OTP
                  </Button>
                </Form>

                <div style={{ height: 16 }} />

                <Form layout="vertical" onFinish={onAuthVerify}>
                  <Row gutter={[16, 16]}>
                    <Col xs={24} md={12} lg={8}>
                      <Form.Item
                        label="OTP"
                        name="otp"
                        rules={[{ required: true, message: "OTP is required" }]}
                      >
                        <Input placeholder="12345" />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={12} lg={8}>
                      <Form.Item
                        label="2FA Password (optional)"
                        name="password"
                      >
                        <Input.Password placeholder="optional" />
                      </Form.Item>
                    </Col>
                  </Row>
                  <Button
                    type="primary"
                    htmlType="submit"
                    disabled={!otpSent}
                    loading={verifyingOtp}
                  >
                    Verify OTP
                  </Button>
                  {!otpSent ? (
                    <Text type="secondary" style={{ marginLeft: 12 }}>
                      Send OTP to enable verification.
                    </Text>
                  ) : null}
                </Form>
              </>
            )}
          </Card>
        </div>

        {dashboardVisible ? (
          <div className="dashboard-grid">
            <Card title="Available Channels" className="grid-card grid-span-2">
              <Table
                columns={availableChatColumns}
                dataSource={availableChats}
                rowKey={(row) => row.id}
                pagination={{ pageSize: 6 }}
                scroll={{ y: 220 }}
              />
            </Card>

            <Card title="Enabled Channels" className="grid-card">
              <List
                bordered
                dataSource={enabledChats}
                locale={{ emptyText: "No enabled chats" }}
                renderItem={(chat) => <List.Item>{chat}</List.Item>}
                className="list-scroll"
              />
              <div style={{ height: 12 }} />
              <Form layout="vertical" onFinish={onAddChat}>
                <Form.Item
                  label="Add Chat"
                  name="chat_identifier"
                  rules={[
                    { required: true, message: "Chat identifier is required" },
                  ]}
                >
                  <Input placeholder="@channel or chat id" />
                </Form.Item>
                <Button type="primary" htmlType="submit">
                  Add Chat
                </Button>
              </Form>
            </Card>

            <Card title="Live Jobs" className="grid-card grid-span-2">
              <Table
                columns={jobColumns}
                dataSource={activeJobs}
                rowKey={(row) => row.message_id}
                pagination={false}
                locale={{ emptyText: "No active jobs" }}
                scroll={{ y: 220 }}
              />
            </Card>
          </div>
        ) : null}
      </Content>
    </Layout>
  );
}
