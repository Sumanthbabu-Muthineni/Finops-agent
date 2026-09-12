import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  headers: {
    'Content-Type': 'application/json'
  }
});

export const sendMessage = async (message, sessionId) => {
  const payload = { message };
  if (sessionId) {
    payload.session_id = sessionId;
  }
  const response = await api.post('/chat', payload);
  return response.data;
};

export const getHealth = async () => {
  const response = await api.get('/health');
  return response.data;
};

export const getVendors = async () => {
  const response = await api.get('/vendors');
  return response.data.vendors || [];
};

export const connectDatabase = async (config, sessionId) => {
  const payload = { ...config, session_id: sessionId };
  const response = await api.post('/db/connect', payload);
  return response.data;
};

export const disconnectDatabase = async (sessionId) => {
  const response = await api.post('/db/disconnect', { session_id: sessionId });
  return response.data;
};

export const getDbStatus = async (sessionId) => {
  const response = await api.get(`/db/status/${sessionId}`);
  return response.data;
};

export const getDbAdvisor = async (sessionId) => {
  const response = await api.get(`/db/advisor/${sessionId}`);
  return response.data;
};
