import React, { useState } from "react";
import {
  Alert,
  Button,
  Card,
  Col,
  Form,
  Input,
  Layout,
  Row,
  Space,
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

  const onAuthStart = async (values) => {
    setError("");
    setAuthStatus("");
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
    } catch (err) {
      setError(err.message || "Failed to send OTP");
    }
  };

  const onAuthVerify = async (values) => {
    setError("");
    setAuthStatus("");
    try {
      const payload = {
        phone_number: values.phone_number,
        otp: values.otp,
        password: values.password || undefined,
      };
      await fetchJson("/auth/verify", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setAuthStatus("Authorized. Scraper will start shortly.");
      setOtpSent(false);
    } catch (err) {
      setError(err.message || "Failed to verify OTP");
    }
  };

  return (
    <Layout className="app-layout">
      <Header className="app-header">
        <Title level={3} style={{ margin: 0 }}>
          Telegram Scrapper
        </Title>
      </Header>
      <Content className="app-content">
        <div className="auth-wrap">
          <Space direction="vertical" style={{ width: "100%" }} size="middle">
            {error ? <Alert message={error} type="error" showIcon /> : null}
            {authStatus ? (
              <Alert message={authStatus} type="success" showIcon />
            ) : null}
          </Space>

          <Card title="Telegram Authentication">
            <Form layout="vertical" onFinish={onAuthStart}>
              <Row gutter={[16, 16]}>
                <Col xs={24} md={12} lg={6}>
                  <Form.Item
                    label="API ID"
                    name="api_id"
                    rules={[{ required: true, message: "API ID is required" }]}
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
                      { required: true, message: "Phone number is required" },
                    ]}
                  >
                    <Input placeholder="+15551234567" />
                  </Form.Item>
                </Col>
              </Row>
              <Button type="primary" htmlType="submit">
                Send OTP
              </Button>
            </Form>

            <div style={{ height: 16 }} />

            <Form layout="vertical" onFinish={onAuthVerify}>
              <Row gutter={[16, 16]}>
                <Col xs={24} md={12} lg={8}>
                  <Form.Item
                    label="Phone Number"
                    name="phone_number"
                    rules={[
                      { required: true, message: "Phone number is required" },
                    ]}
                  >
                    <Input placeholder="+15551234567" />
                  </Form.Item>
                </Col>
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
                  <Form.Item label="2FA Password (optional)" name="password">
                    <Input.Password placeholder="optional" />
                  </Form.Item>
                </Col>
              </Row>
              <Button type="primary" htmlType="submit" disabled={!otpSent}>
                Verify OTP
              </Button>
              {!otpSent ? (
                <Text type="secondary" style={{ marginLeft: 12 }}>
                  Send OTP to enable verification.
                </Text>
              ) : null}
            </Form>
          </Card>
        </div>
      </Content>
    </Layout>
  );
}
