import os, sys, socket, urlparse

###

class socket_uri(object):
	'''
	Socket factory that is configured using socket URI.
	This is actually quite generic implementation - not specific to console-server IPC communication.
	'''

	# Configure urlparse
	if 'unix' not in urlparse.uses_query: urlparse.uses_query.append('unix')
	if 'tcp' not in urlparse.uses_query: urlparse.uses_query.append('tcp')

	def __init__(self, uri):
		self.uri = urlparse.urlparse(uri.strip())
		self.uriquery = dict(urlparse.parse_qsl(self.uri.query))

		self.protocol = self.uri.scheme.lower()
		if self.protocol == 'tcp':
			try:
				_port = self.uri.port
			except ValueError:
				raise RuntimeError("Invalid port number in socket URI {0}".format(uri))

			if self.uri.path != '': raise RuntimeError("Path has to be empty in socket URI {0}".format(uri))

		elif self.protocol == 'unix':
			if sys.platform == 'win32':
				os.error("UNIX sockets are not supported on this plaform")
				raise RuntimeError("UNIX sockets are not supported on this plaform ({0})".format(uri))
			if self.uri.netloc != '':
				# Special case of situation when netloc is not empty (path is relative)
				self.uri = self.uri._replace(netloc='', path=self.uri.netloc + self.uri.path)

		else:
			raise RuntimeError("Unknown/unsupported protocol '{0}' in socket URI {1}".format(self.protocol, uri))


	def create_socket_listen(self):
		'''Return list of socket created in listen mode.
		The trick here is that for single host/port combinations, multiple listen socket can be created (e.g. IPv4 vs IPv6)
		'''
		retsocks = []

		if self.protocol == 'tcp':
			for family, socktype, proto, canonname, sockaddr in socket.getaddrinfo(self.uri.hostname, self.uri.port, 0, socket.SOCK_STREAM):
				s = socket.socket(family, socktype, proto)
				
				if self.uriquery.get("ssl", None) == "1":
					import ssl
					certfile, keyfile, cert_reqs, ca_certs = self._get_ssl_params()
					s = ssl.wrap_socket(s, keyfile=keyfile, certfile=certfile, server_side=True, ca_certs=ca_certs, cert_reqs=cert_reqs)
					
				s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) 
				s.bind(sockaddr)
				retsocks.append(s)

		elif self.protocol == 'unix':
			mode = self.uriquery.get('mode',None)
			if mode is None: mode = 0o600
			else: mode = int(mode,8)
			oldmask = os.umask(mode ^ 0o777)
			s = _deleteing_unix_socket()
			s.bind(self.uri.path)
			os.umask(oldmask)

			retsocks.append(s)

		else:
			raise RuntimeError("Unknown/unsupported protocol '{0}'".format(self.protocol))

		return retsocks


	def create_socket_connect(self):
		if self.protocol == 'tcp':
			errors = []
			for family, socktype, proto, canonname, sockaddr in socket.getaddrinfo(self.uri.hostname, self.uri.port, 0, socket.SOCK_STREAM):
				try:
					s = socket.socket(family, socktype, proto)
					if self.uriquery.get("ssl", None) == "1":
						import ssl
						certfile, keyfile, cert_reqs, ca_certs = self._get_ssl_params()
						
						s = ssl.wrap_socket(s,
							keyfile=keyfile,
							certfile=certfile,
							ca_certs=ca_certs,
							cert_reqs=ssl.CERT_REQUIRED
						)
					s.connect(sockaddr)
					return s
				except Exception, e:
					errors.append("{0}: {1}".format(sockaddr, e))
					continue
			raise RuntimeError("Connection failed: {0}".format('; '.join(errors)))

		elif self.protocol == 'unix':
			s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
			s.connect(self.uri.path)
			return s

		else:
			raise RuntimeError("Unknown/unsuported protocol '{0}'".format(self.protocol))
	
	
	def _get_ssl_params(self):
		'''
		Helper function to read the ssl related parameter from connection URI
		Besides returing the configuration values, this function raises RuntimeError if one of the required
		configuration attributes is missing.
		
		@return tuple: certfile, keyfile, cert_reqs, ca_certs
		'''
		import ssl
		certfile = self.uriquery.get("certfile", None)
		if certfile is None:
			raise RuntimeError("certfile parametr has to be provided in URI if ssl=1")
		# Keyfile can be None -- in that case the private key is expected to be part of the certificate
		keyfile = self.uriquery.get("keyfile", None)
		
		sslauth = self.uriquery.get("sslauth", None)
		cert_reqs = ssl.CERT_NONE
		ca_certs = None
		if sslauth != "0":
			cert_reqs = ssl.CERT_REQUIRED
			ca_certs = self.uriquery.get("cacerts", None)
			if ca_certs is None:
				raise RuntimeError("cacerts parametr has to be provided in URI if ssl=1")
		
		return certfile, keyfile, cert_reqs, ca_certs

###

class _deleteing_unix_socket(socket.socket):
	'''
This class is used as wrapper to socket object that represent listening UNIX socket.
It added ability to delete socket file when destroyed.

It is basically used only on server side of UNIX socket.
	'''

	def __init__(self):
		socket.socket.__init__(self, socket.AF_UNIX, socket.SOCK_STREAM)
		self.__sockfile = None


	def __del__(self):
		self.__delsockfile()


	def close(self):
		socket.socket.close(self)
		self.__delsockfile()


	def bind(self, fname):
		socket.socket.bind(self, fname)
		self.__sockfile = fname


	def __delsockfile(self):
		if self.__sockfile is not None:
			fname = self.__sockfile
			self.__sockfile = None
			os.unlink(fname)
			assert not os.path.isfile(fname)
