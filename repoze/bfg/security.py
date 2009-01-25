from zope.interface import implements
from zope.component import queryUtility

from repoze.bfg.location import lineage

from repoze.bfg.interfaces import ISecurityPolicy
from repoze.bfg.interfaces import IViewPermission
from repoze.bfg.interfaces import IViewPermissionFactory

Everyone = 'system.Everyone'
Authenticated = 'system.Authenticated'
Allow = 'Allow'
Deny = 'Deny'

def has_permission(permission, context, request):
    """ Provided a permission (a string or unicode object), a context
    (a model instance) and a request object, return an instance of
    ``Allowed`` if the permission is granted in this context to the
    user implied by the request. Return an instance of ``Denied`` if
    this permission is not granted in this context to this user.  This
    delegates to the current security policy.  Return True
    unconditionally if no security policy has been configured in this
    application."""
    policy = queryUtility(ISecurityPolicy)
    if policy is None:
        return Allowed('No security policy in use.')
    return policy.permits(context, request, permission)

def authenticated_userid(request):
    """ Return the userid of the currently authenticated user or
    ``None`` if there is no security policy in effect or there is no
    currently authenticated user"""
    policy = queryUtility(ISecurityPolicy)
    if policy is None:
        return None
    return policy.authenticated_userid(request)

def effective_principals(request):
    """ Return the list of 'effective' principal identifiers for the
    request.  This will include the userid of the currently
    authenticated user if a user is currently authenticated. If no
    security policy is in effect, this will return an empty sequence."""
    policy = queryUtility(ISecurityPolicy)
    if policy is None:
        return []
    return policy.effective_principals(request)

def principals_allowed_by_permission(context, permission):
    """ Provided a context (a model object), and a permission (a
    string or unicode object), return a sequence of principal ids that
    possess the permission in the context.  If no security policy is
    in effect, this will return a sequence with the single value
    representing ``Everyone`` (the special principal identifier
    representing all principals).  Note that even if a security policy
    *is* in effect, some security policies may not implement the
    required machinery for this function; those will cause a
    ``NotImplementedError`` exception to be raised when this function
    is invoked."""
    policy = queryUtility(ISecurityPolicy)
    if policy is None:
        return [Everyone]
    return policy.principals_allowed_by_permission(context, permission)

class ACLSecurityPolicy(object):
    implements(ISecurityPolicy)
    
    def __init__(self, get_principals):
        self.get_principals = get_principals

    def permits(self, context, request, permission):
        """ Return ``ACLAllowed`` if the policy permits access,
        ``ACLDenied`` if not. """
        principals = set(self.effective_principals(request))

        for location in lineage(context):
            try:
                acl = location.__acl__
            except AttributeError:
                continue

            for ace in acl:
                ace_action, ace_principal, ace_permissions = ace
                if ace_principal in principals:
                    if not hasattr(ace_permissions, '__iter__'):
                        ace_permissions = [ace_permissions]
                    if permission in ace_permissions:
                        if ace_action == Allow:
                            return ACLAllowed(ace, acl, permission,
                                              principals, location)
                        else:
                            return ACLDenied(ace, acl, permission,
                                             principals, location)

            # default deny if no ACE matches in the ACL found
            result = ACLDenied(None, acl, permission, principals, location)
            return result
        
        # default deny if no ACL in lineage at all
        return ACLDenied(None, None, permission, principals, context)

    def authenticated_userid(self, request):
        principals = self.get_principals(request)
        if principals:
            return principals[0]

    def effective_principals(self, request):
        effective_principals = [Everyone]
        principal_ids = self.get_principals(request)

        if principal_ids:
            effective_principals.append(Authenticated)
            effective_principals.extend(principal_ids)

        return effective_principals

    def principals_allowed_by_permission(self, context, permission):
        for location in lineage(context):
            try:
                acl = location.__acl__
            except AttributeError:
                continue

            allowed = {}

            for ace_action, ace_principal, ace_permissions in acl:
                if ace_action == Allow:
                    if not hasattr(ace_permissions, '__iter__'):
                        ace_permissions = [ace_permissions]
                    if permission in ace_permissions:
                        allowed[ace_principal] = True
            return sorted(allowed.keys())

        return []

def get_remoteuser(request):
    user_id = request.environ.get('REMOTE_USER')
    if user_id:
        return [user_id]
    return []

def RemoteUserACLSecurityPolicy():
    """ A security policy which:

    - examines the request.environ for the REMOTE_USER variable and
      uses any non-false value as a principal id for this request.

    - uses an ACL-based authorization model which attempts to find an
      ACL on the context, and which returns ``Allowed`` from its
      'permits' method if the ACL found grants access to the current
      principal.  It returns ``Denied`` if permission was not granted
      (either explicitly via a deny or implicitly by not finding a
      matching ACE action).  An ACL is an ordered sequence of ACE
      tuples, e.g.  ``[(Allow, Everyone, 'read'), (Deny, 'george',
      'write')]``.  ACLs stored on model instance objects as their
      __acl__ attribute will be used by the security machinery to
      grant or deny access.

    Enable this security policy by adding the following to your
    application's ``configure.zcml``:

    .. code-block:: xml

       <utility
        provides="repoze.bfg.interfaces.ISecurityPolicy"
        factory="repoze.bfg.security.RemoteUserACLSecurityPolicy"
        />

    """
    return ACLSecurityPolicy(get_remoteuser)

def get_who_principals(request):
    identity = request.environ.get('repoze.who.identity')
    if not identity:
        return []
    principals = [identity['repoze.who.userid']]
    principals.extend(identity.get('groups', []))
    return principals

def RepozeWhoIdentityACLSecurityPolicy():
    """
    A security policy which:

    - examines the request.environ for the ``repoze.who.identity``
      dictionary.  If one is found, the principal ids for the request
      are composed of ``repoze.who.identity['repoze.who.userid']``
      plus ``repoze.who.identity.get('groups', [])``.

    - uses an ACL-based authorization model which attempts to find an
      ACL on the context, and which returns ``Allowed`` from its
      'permits' method if the ACL found grants access to the current
      principal.  It returns ``Denied`` if permission was not granted
      (either explicitly via a deny or implicitly by not finding a
      matching ACE action).  An ACL is an ordered sequence of ACE
      tuples, e.g.  ``[(Allow, Everyone, 'read'), (Deny, 'george',
      'write')]``.  ACLs stored on model instance objects as their
      __acl__ attribute will be used by the security machinery to
      grant or deny access.

    Enable this security policy by adding the following to your
    application's ``configure.zcml``:

    .. code-block:: xml

       <utility
        provides="repoze.bfg.interfaces.ISecurityPolicy"
        factory="repoze.bfg.security.RepozeWhoIdentityACLSecurityPolicy"
        />
    """
    return ACLSecurityPolicy(get_who_principals)

class PermitsResult(int):
    def __new__(cls, s, *args):
        inst = int.__new__(cls, cls.boolval)
        inst.s = s
        inst.args = args
        return inst
        
    @property
    def msg(self):
        return self.s % self.args

    def __str__(self):
        return self.msg

    def __repr__(self):
        return '<%s instance at %s with msg %r>' % (self.__class__.__name__,
                                                    id(self),
                                                    self.msg)

class Denied(PermitsResult):
    """ An instance of ``Denied`` is returned when a security policy
    or other ``repoze.bfg`` code denies an action unlrelated to an ACL
    check.  It evaluates equal to all boolean false types.  It has an
    attribute named ``msg`` describing the circumstances for the deny."""
    boolval = 0

class Allowed(PermitsResult):
    """ An instance of ``Allowed`` is returned when a security policy
    or other ``repoze.bfg`` code allows an action unrelated to an ACL
    check.  It evaluates equal to all boolean true types.  It has an
    attribute named ``msg`` describing the circumstances for the
    allow."""
    boolval = 1

class ACLPermitsResult(int):
    def __new__(cls, ace, acl, permission, principals, context):
        inst = int.__new__(cls, cls.boolval)
        inst.permission = permission
        inst.ace = ace
        inst.acl = acl
        inst.principals = principals
        inst.context = context
        return inst

    @property
    def msg(self):
        s = ('%s permission %r via ACE %r in ACL %r on context %r for '
             'principals %r')
        return s % (self.__class__.__name__,
                    self.permission,
                    self.ace,
                    self.acl,
                    self.context,
                    self.principals)

    def __str__(self):
        return self.msg

    def __repr__(self):
        return '<%s instance at %s with msg %r>' % (self.__class__.__name__,
                                                    id(self),
                                                    self.msg)

class ACLDenied(ACLPermitsResult):
    """ An instance of ``ACLDenied`` represents that a security check
    made explicitly against ACL was denied.  It evaluates equal to all
    boolean false types.  It also has attributes which indicate which
    acl, ace, permission, principals, and context were involved in the
    request.  Its __str__ method prints a summary of these attributes
    for debugging purposes.  The same summary is available as he
    ``msg`` attribute."""
    boolval = 0

class ACLAllowed(ACLPermitsResult):
    """ An instance of ``ACLDenied`` represents that a security check
    made explicitly against ACL was allowed.  It evaluates equal to
    all boolean true types.  It also has attributes which indicate
    which acl, ace, permission, principals, and context were involved
    in the request.  Its __str__ method prints a summary of these
    attributes for debugging purposes.  The same summary is available
    as he ``msg`` attribute."""
    boolval = 1

class ViewPermission(object):
    implements(IViewPermission)
    def __init__(self, context, request, permission_name):
        self.context = context
        self.request = request
        self.permission_name = permission_name
    
    def __call__(self, security_policy, debug_info=None):
        return security_policy.permits(self.context,
                                       self.request,
                                       self.permission_name)

    def __repr__(self):
        view_name = getattr(self.request, 'view_name', None)
        return '<Permission at %s named %r for %r>' % (id(self),
                                                       self.permission_name,
                                                       view_name)
        
class ViewPermissionFactory(object):
    implements(IViewPermissionFactory)
    def __init__(self, permission_name):
        self.permission_name = permission_name

    def __call__(self, context, request):
        return ViewPermission(context, request, self.permission_name)

class Unauthorized(Exception):
    pass


    
    
