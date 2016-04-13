from abc import abstractmethod

from kernel_exp_family.estimators.estimator_oop import EstimatorBase
from kernel_exp_family.tools.assertions import assert_array_shape
from kernel_exp_family.kernels.kernels import gaussian_kernel_hessians

import numpy as np

def SE(x, y, l=2):
    # ASSUMES COLUMN VECTORS
    diff = x - y;
    return np.squeeze(np.exp(-np.dot(diff.T, diff) / (2 * l ** 2)))

def SE_dx(x, y, l=2):
    return SE(x, y, l) * (y - x) / l ** 2

def SE_dx_dx(x, y, l=2):
    # Doing SE(x,y,l)*((y-x)**2/l**4 - 1/l**2) does not work!
    return SE(x, y, l) * (y - x) ** 2 / l ** 4 - SE(x, y, l) / l ** 2

def SE_dx_dy(x, y, l=2):
    SE_tmp = SE(x, y, l)
    term1 = SE_tmp * np.eye(x.size) / l ** 2
    term2 = SE_tmp * np.dot((x - y), (x - y).T) / l ** 4
    return term1 - term2

def SE_dx_dx_dy(x, y, l=2):
    SE_tmp = SE(x, y, l)
    term1 = SE_tmp * np.dot((x - y) ** 2, (x - y).T) / l ** 6
    term2 = SE_tmp * 2 * np.diag((x - y)[:, 0]) / l ** 4
    term3 = SE_tmp * np.repeat((x - y), x.size, 1).T / l ** 4
    return term1 - term2 - term3

def SE_dx_dx_dy_dy(x, y, l=2):
    SE_tmp = SE(x, y, l)
    term1 = SE_tmp * np.dot((x - y), (x - y).T) ** 2 / l ** 8
    term2 = SE_tmp * 6 * np.diagflat((x - y) ** 2) / l ** 6  # diagonal (x-y)
    term3 = (1 - np.eye(x.size)) * SE_tmp * np.repeat((x - y), x.size, 1) ** 2 / l ** 6  # (x_i-y_i)^2 off-diagonal 
    term4 = (1 - np.eye(x.size)) * SE_tmp * np.repeat((x - y).T, x.size, 0) ** 2 / l ** 6  # (x_j-y_j)^2 off-diagonal
    term5 = SE_tmp * (1 + 2 * np.eye(x.size)) / l ** 4
    
    return term1 - term2 - term3 - term4 + term5


def SE_dx_i_dx_j(x, y, l=2):
    """ Matrix of \frac{\partial k}{\partial x_i \partial x_j}"""
    pairwise_dist = (y-x).dot((y-x).T)

    term1 = SE(x, y, l)*pairwise_dist/l**4
    term2 = SE(x, y, l)*np.eye(pairwise_dist.shape[0])/l**2

    return term1 - term2


def SE_dx_i_dx_i_dx_j(x, y, l=2):
    """ Matrix of \frac{\partial k}{\partial x_i^2 \partial x_j}"""
    pairwise_dist_squared_i = ((y-x)**2).dot((y-x).T)
    row_repeated_distances = np.repeat((y-x).T,
                                       pairwise_dist_squared_i.shape[0],
                                       axis=0)

    term1 = SE(x, y, l)*pairwise_dist_squared_i/l**6
    term2 = SE(x, y, l)*row_repeated_distances/l**4
    term3 = term2*2*np.eye(pairwise_dist_squared_i.shape[0])

    return term1 - term2 - term3

def compute_h(kernel_dx_dx_dy, data):
    n, d = data.shape
    h = np.zeros((n, d))
    for b in range(n):
        for a in range(n):
            h[b, :] += np.sum(kernel_dx_dx_dy(data[a, :].reshape(-1, 1), data[b, :].reshape(-1, 1)), axis=0)
            
    return h / n


def compute_lower_right_submatrix(all_hessians, N, lmbda):
    return np.dot(all_hessians,all_hessians)/N + lmbda*all_hessians

def compute_first_row(h, all_hessians, n, lmbda):
    return np.dot(h, all_hessians)/n + lmbda*h

def compute_RHS(h, xi_norm_2):
    b = np.zeros(h.size+1)
    b[0] = -xi_norm_2
    b[1:] = -h.reshape(-1)

    return b

def compute_xi_norm_2(kernel_dx_dx_dy_dy, data):
    n, _ = data.shape
    norm_2 = 0
    for a in range(n):
        for b in range(n):
            x = data[a, :].reshape(-1, 1)
            y = data[b, :].reshape(-1, 1)
            norm_2 += np.sum(kernel_dx_dx_dy_dy(x, y))
            
    return norm_2 / n ** 2


def build_system(X, sigma, lmbda):
    l = np.sqrt(np.float(sigma) / 2)
    
    n, d = X.shape

    SE_dx_dx_dy_l = lambda x, y: SE_dx_dx_dy(x, y, l)
    SE_dx_dx_dy_dy_l = lambda x, y: SE_dx_dx_dy_dy(x, y, l)
    
    h = compute_h(SE_dx_dx_dy_l, X).reshape(-1)
    all_hessians = gaussian_kernel_hessians(X, sigma=sigma)
    xi_norm_2 = compute_xi_norm_2(SE_dx_dx_dy_dy_l, X)
    
    A = np.zeros((n * d + 1, n * d + 1))
    A[0,0] = np.dot(h, h)/n + lmbda*xi_norm_2
    A[1:, 1:] = compute_lower_right_submatrix(all_hessians, n, lmbda)
    
    A[0, 1:] = compute_first_row(h, all_hessians, n, lmbda)
    A[1:, 0] = A[0,1:]
    
    b = compute_RHS(h, xi_norm_2)
    
    return A, b

def fit(X, sigma, lmbda):
    n, d = X.shape
    A, b = build_system(X, sigma, lmbda)
    x = np.linalg.solve(A, b)
    alpha = x[0]
    beta = x[1:].reshape(n, d)
    return alpha, beta

def log_pdf(x, X, sigma, alpha, beta):
    _, D = X.shape
    assert_array_shape(x, ndim=1, dims={0: D})
    N = len(X)
    
    l = np.sqrt(np.float(sigma) / 2)
    SE_dx_dx_l = lambda x, y : SE_dx_dx(x, y, l)
    SE_dx_l = lambda x, y: SE_dx(x, y, l)
    
    xi = 0
    betasum = 0
    for a in range(N):
        x_a = X[a, :].reshape(-1, 1)
        xi += np.sum(SE_dx_dx_l(x.reshape(-1, 1), x_a)) / N
        gradient_x_xa= np.squeeze(SE_dx_l(x.reshape(-1, 1), x_a))
        betasum += np.dot(gradient_x_xa, beta[a, :])
    
    return np.float(alpha * xi + betasum)

def grad(x, X, sigma, alpha, beta):
    N, D = X.shape
    assert_array_shape(x, ndim=1, dims={0: D})
    
    x = x.reshape(-1,1)
    l = np.sqrt(np.float(sigma) / 2)

    xi_grad = 0
    betasum_grad = 0
    for a in range(N):
        x_a = X[a, :].reshape(-1, 1)

        xi_grad += np.sum(SE_dx_i_dx_i_dx_j(x, x_a, l), axis=0) / N
        left_arg_hessian = SE_dx_i_dx_j(x, x_a, l)
        betasum_grad += beta[a, :].dot(left_arg_hessian)

    return alpha * xi_grad + betasum_grad

class KernelExpFullGaussian(EstimatorBase):
    def __init__(self, sigma, lmbda, D, N):
        self.sigma = sigma
        self.lmbda = lmbda
        self.D = D
        self.N = N
        
        # initial RKHS function is flat
        self.alpha = 0
        self.beta = np.zeros(D * N)
        self.X = np.zeros((0, D))
    
    def fit(self, X):
        assert_array_shape(X, ndim=2, dims={1: self.D})
        
        # sub-sample if data is larger than previously set N
        if len(X) > self.N:
            inds = np.random.permutation(len(X))[:self.N]
            self.X = X[inds]
        else:
            self.X = np.copy(X)
            
        self.fit_wrapper_()
    
    @abstractmethod
    def fit_wrapper_(self):
        self.alpha, self.beta = fit(self.X, self.sigma, self.lmbda)
    
    def log_pdf(self, x):
        return log_pdf(x, self.X, self.sigma, self.alpha, self.beta)

    def grad(self, x):
        return grad(x, self.X, self.sigma, self.alpha, self.beta)

    def log_pdf_multiple(self, X):
        return np.array([self.log_pdf(x) for x in X])
    
    def objective(self, X):
        assert_array_shape(X, ndim=2, dims={1: self.D})
        return 0.

    def get_parameter_names(self):
        return ['sigma', 'lmbda']